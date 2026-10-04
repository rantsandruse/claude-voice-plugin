"""Compare local STT backends on the same clips: latency, accuracy, memory.

    python scripts/bench_stt.py make-samples DIR   # synthetic clips via `say`
    python scripts/bench_stt.py record DIR         # record your own voice
    python scripts/bench_stt.py run DIR [--providers SPEC ...] [--repeats N]

A clip is NAME.wav (16 kHz mono) plus NAME.txt with the reference text; an
empty .txt marks a silence clip, where any output counts as a hallucination.

Provider SPECs: whisper_local:MODEL, whisper_cpp:MODEL, parakeet:HF_ID.
Each provider runs in its own subprocess so load time and memory are isolated.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import re
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SAMPLE_RATE = 16000

DEFAULT_PROVIDERS = [
    "whisper_local:small",              # what the daemon uses today
    "whisper_cpp:small",                # same model, Metal engine
    "whisper_cpp:large-v3-turbo-q5_0",
    "parakeet:mlx-community/parakeet-tdt-0.6b-v3",
]

# Code-dictation style prompts. Numbers are avoided so "three" vs "3" doesn't
# count as an error.
PROMPTS = {
    "short_tests": "run the tests",
    "short_bug": "fix the bug in the daemon",
    "short_push": "commit the changes and push the branch",
    "short_func": "what does this function do",
    "med_rename": "rename the transcribe audio method and update every caller in the daemon",
    "med_test": "add a unit test that checks the recorder returns nothing for very short clips",
    "med_config": "read the config file and tell me which speech provider is selected by default",
    "long_refactor": (
        "I want to refactor the speech to text layer so every provider shares one "
        "cleanup function. Move the hallucination filter into the text cleaner module, "
        "update the deepgram and whisper providers to call it, and make sure the "
        "existing tests still pass before you commit anything. If something breaks, "
        "stop and explain what happened instead of guessing."
    ),
}


# --- clip I/O ---------------------------------------------------------------

def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need 16 kHz mono 16-bit WAV")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _write_wav(path: Path, audio_i16: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio_i16.tobytes())


def _clips(directory: Path) -> list[tuple[str, Path, str]]:
    out = []
    for wav in sorted(directory.glob("*.wav")):
        ref = wav.with_suffix(".txt")
        out.append((wav.stem, wav, ref.read_text().strip() if ref.exists() else ""))
    if not out:
        raise SystemExit(f"no .wav clips in {directory}")
    return out


def make_samples(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in PROMPTS.items():
        wav = directory / f"say_{name}.wav"
        subprocess.run(
            ["say", "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@16000", text],
            check=True,
        )
        wav.with_suffix(".txt").write_text(text + "\n")
    _write_wav(directory / "silence.wav", np.zeros(2 * SAMPLE_RATE, dtype=np.int16))
    (directory / "silence.txt").write_text("")
    print(f"wrote {len(PROMPTS) + 1} clips to {directory}")


def record(directory: Path) -> None:
    import sounddevice as sd

    directory.mkdir(parents=True, exist_ok=True)
    print("For each prompt: Enter to start, read it naturally, Enter to stop. Ctrl-C to quit.\n")
    items = list(PROMPTS.items()) + [("silence", "")]
    for name, text in items:
        print(f"[{name}] {text or '(stay silent for ~2 seconds)'}")
        input("  Enter to start...")
        chunks: list[np.ndarray] = []
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            callback=lambda indata, *_: chunks.append(indata.copy()),
        )
        with stream:
            input("  recording — Enter to stop")
        audio = np.concatenate(chunks).reshape(-1) if chunks else np.zeros(0, np.int16)
        _write_wav(directory / f"me_{name}.wav", audio)
        (directory / f"me_{name}.txt").write_text(text + ("\n" if text else ""))
        print(f"  saved {len(audio) / SAMPLE_RATE:.1f}s\n")


# --- metrics ----------------------------------------------------------------

def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9']+", " ", text.lower()).split()


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """(edit distance in words, reference word count)."""
    r, h = _words(ref), _words(hyp)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1], len(r)


def _footprint_mb() -> tuple[float, float]:
    """(current, lifetime peak) physical footprint — the number Activity
    Monitor shows. Unlike RSS it includes Metal/GPU allocations in unified
    memory, which is where whisper.cpp and MLX keep the model."""
    buf = (ctypes.c_uint64 * 64)()
    libc = ctypes.CDLL("libc.dylib")
    if libc.proc_pid_rusage(ctypes.c_int(__import__("os").getpid()), 4, buf) != 0:
        return float("nan"), float("nan")
    # rusage_info_v4: 16-byte uuid, then uint64 fields. phys_footprint is
    # field 7 and lifetime_max_phys_footprint is field 28 after the uuid.
    return buf[2 + 7] / 2**20, buf[2 + 28] / 2**20


# --- worker (one provider per process) ---------------------------------------

def _make_provider(spec: str):
    kind, _, model = spec.partition(":")
    if kind == "whisper_local":
        from claude_voice.config import WhisperLocalConfig
        from claude_voice.stt.whisper_local import WhisperLocalProvider
        return WhisperLocalProvider(WhisperLocalConfig(model=model))
    if kind == "whisper_cpp":
        from claude_voice.config import WhisperCppConfig
        from claude_voice.stt.whisper_cpp import WhisperCppProvider
        return WhisperCppProvider(WhisperCppConfig(model=model))
    if kind == "parakeet":
        from claude_voice.config import ParakeetConfig
        from claude_voice.stt.parakeet import ParakeetProvider
        return ParakeetProvider(ParakeetConfig(model=model))
    raise SystemExit(f"unknown provider kind in {spec!r}")


def worker(spec: str, directory: Path, repeats: int) -> None:
    clips = [(name, _read_wav(wav), ref) for name, wav, ref in _clips(directory)]
    provider = _make_provider(spec)

    t = time.perf_counter()
    provider._model_get()
    load_s = time.perf_counter() - t
    t = time.perf_counter()
    provider.warmup()
    warmup_s = time.perf_counter() - t

    results = []
    for name, audio, ref in clips:
        times, text = [], ""
        for _ in range(repeats):
            t = time.perf_counter()
            text = provider.transcribe_audio(audio, SAMPLE_RATE)
            times.append(time.perf_counter() - t)
        results.append({
            "clip": name, "audio_s": len(audio) / SAMPLE_RATE, "ref": ref,
            "text": text, "latency_s": statistics.median(times),
        })
    current_mb, peak_mb = _footprint_mb()
    json.dump({
        "spec": spec, "load_s": load_s, "warmup_s": warmup_s,
        "footprint_mb": current_mb, "peak_footprint_mb": peak_mb, "clips": results,
    }, sys.stdout)


# --- report -----------------------------------------------------------------

def _bucket(name: str) -> str:
    for b in ("short", "med", "long", "silence"):
        if b in name:
            return b
    return "other"


def run(directory: Path, specs: list[str], repeats: int, out: Path | None, timeout: int) -> None:
    reports = []
    for spec in specs:
        print(f"running {spec} ...", file=sys.stderr, flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, __file__, "_worker", spec, str(directory), str(repeats)],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            # Whisper can get stuck in a repetition loop on bad input; don't
            # let one provider stall the whole comparison.
            print(f"  TIMED OUT after {timeout}s", file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(f"  FAILED:\n{proc.stderr[-2000:]}", file=sys.stderr)
            continue
        reports.append(json.loads(proc.stdout))

    if out:
        out.write_text(json.dumps(reports, indent=2))

    print("\n## Summary (latency = median wall time per clip after warmup)\n")
    print("| provider | load s | short ms | med ms | long ms | WER | silence | mem MB (peak) |")
    print("|---|---|---|---|---|---|---|---|")
    for r in reports:
        by = {}
        for c in r["clips"]:
            by.setdefault(_bucket(c["clip"]), []).append(c)
        lat = lambda b: (f"{statistics.mean(c['latency_s'] for c in by[b]) * 1000:.0f}"
                         if b in by else "-")
        errs = [word_errors(c["ref"], c["text"]) for c in r["clips"] if c["ref"]]
        wer = sum(e for e, _ in errs) / max(1, sum(n for _, n in errs))
        silent = [c for c in r["clips"] if not c["ref"]]
        sil = ("-" if not silent else
               "clean" if all(not c["text"] for c in silent) else
               "; ".join(repr(c["text"]) for c in silent if c["text"]))
        print(f"| {r['spec']} | {r['load_s']:.1f} | {lat('short')} | {lat('med')} | "
              f"{lat('long')} | {wer:.1%} | {sil} | "
              f"{r['footprint_mb']:.0f} ({r['peak_footprint_mb']:.0f}) |")

    print("\n## Transcripts that differ from the reference\n")
    for r in reports:
        for c in r["clips"]:
            if c["ref"] and _words(c["ref"]) != _words(c["text"]):
                print(f"- **{r['spec']}** `{c['clip']}`: {c['text']!r}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_worker":
        worker(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]))
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make-samples").add_argument("dir", type=Path)
    sub.add_parser("record").add_argument("dir", type=Path)
    rp = sub.add_parser("run")
    rp.add_argument("dir", type=Path)
    rp.add_argument("--providers", nargs="+", default=DEFAULT_PROVIDERS)
    rp.add_argument("--repeats", type=int, default=3)
    rp.add_argument("--json", type=Path, help="also write raw results here")
    rp.add_argument("--timeout", type=int, default=600, help="seconds per provider")
    args = ap.parse_args()
    if args.cmd == "make-samples":
        make_samples(args.dir)
    elif args.cmd == "record":
        record(args.dir)
    else:
        run(args.dir, args.providers, args.repeats, args.json, args.timeout)


if __name__ == "__main__":
    main()
