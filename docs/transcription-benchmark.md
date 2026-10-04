# Transcription benchmark: faster-whisper vs whisper.cpp

*Measured 2026-10-04. Raw results are in [`benchmarks/2026-10-04/`](benchmarks/2026-10-04/).*

## TL;DR

Moving push-to-talk transcription from **faster-whisper on the CPU** to **whisper.cpp on the Apple GPU (Metal)**, with the *same* Whisper `small` model, made transcription about **4–5× faster** with **word-for-word identical output**:

- A short spoken command ("Run the tests") went from **~1.1 s to ~0.23 s** after releasing the key.
- A 20-second dictated paragraph went from **~1.9–2.7 s to ~0.6 s**.
- The old engine had a floor of about one second even for a two-word command. The new engine's floor is about a quarter of a second.

The engine changed; the model and accuracy didn't.

Of the four local setups measured (faster-whisper, whisper.cpp `small`, whisper.cpp `large-v3-turbo`, Parakeet), whisper.cpp `small` was the best fit for an 8 GB Mac. Parakeet was ~100 ms faster but used 3.5× the memory and made more errors, and turbo was no faster than the old CPU setup.

## Setup

| | |
|---|---|
| Machine | MacBook with Apple M3 (10-core GPU, Metal 3), 8 GB unified memory |
| OS | macOS 14.1.1 |
| Python | 3.12.7 |
| Old engine | faster-whisper 1.2.1 (CTranslate2 4.8.1), CPU, int8 |
| New engine | whisper.cpp via pywhispercpp 1.5.1, Metal backend (Core ML off) |
| Also tested | parakeet-mlx 0.5.3 (MLX 0.32.3) |
| Model | Whisper `small`, English, greedy decoding (beam size 1), no conditioning on previous text |

## Method

- **Script:** `scripts/bench_stt.py`.
- **Isolation:** each engine runs in its own subprocess, so load time and memory don't bleed between models.
- **Warmup excluded:** the model is loaded and warmed up first; timings start after that, matching the daemon, which preloads at startup.
- **Repeats:** each clip is transcribed 3 times and the **median** wall-clock time is reported. That's the time from handing over the audio to getting text back, which is what you feel after releasing the key.
- **Memory:** the process's physical footprint (the number Activity Monitor shows), which includes GPU allocations in unified memory.
- **Clips:**
  - **Voice:** my own voice through the MacBook mic, reading code-dictation prompts.
  - **Synthetic:** the same prompts spoken by macOS's `say`, as a clean reference.
- **"Before/after VAD":** whisper.cpp initially returned `[BLANK_AUDIO]` or "Thank you" on silent audio. Silence trimming (silero VAD) was added before transcription, with the same settings faster-whisper uses. Speech clips are unaffected; see [Silent presses](#silent-presses).

## Results: my voice (shipping configuration, after VAD)

| Clip | Audio length | faster-whisper (CPU) | whisper.cpp (Metal) | Speedup | Same text? |
|---|---|---|---|---|---|
| "Run the tests" | 2.6 s | 1,160 ms | **229 ms** | 5.1× | ✅ |
| "Commit the changes and push the branch" | 4.4 s | 1,163 ms | **278 ms** | 4.2× | ✅ |
| "Read the config file and tell me which speech provider is selected by default" | 4.4 s | 1,270 ms | **299 ms** | 4.2× | ✅ |
| Refactoring request (paragraph) | 19.8 s | 2,703 ms | **638 ms** | 4.2× | ✅ |
| **Total** | | **6,295 ms** | **1,444 ms** | **4.4×** | |

### As a fraction of speaking time

| Clip | faster-whisper | whisper.cpp |
|---|---|---|
| 2.6 s command | 0.44× (44% of speaking time) | 0.09× |
| 19.8 s paragraph | 0.14× | 0.03× |

### Run-to-run variation

An earlier run of the same clips gave 4.7× / 4.6× / 4.1× / 3.3× (total 3.9×). The CPU engine varied the most: the 20 s paragraph took 1,898 ms in one run and 2,703 ms in the other. whisper.cpp stayed within about ±10%. **The fair summary is "4–5× faster".**

## Results: all engines (my voice, before VAD)

| Engine | "Run the tests" | Config sentence | 20 s paragraph | Word errors | Memory |
|---|---|---|---|---|---|
| faster-whisper `small` (CPU) | 1,098 ms | 1,214 ms | 1,898 ms | 3.7% | 0.4 GB (0.7 peak) |
| **whisper.cpp `small` (Metal)** | **232 ms** | **294 ms** | **583 ms** | **3.7%** | 0.8 GB |
| whisper.cpp `large-v3-turbo-q5_0` (Metal) | 1,113 ms | 1,141 ms | 1,308 ms | 3.7% | 0.7 GB |
| Parakeet TDT 0.6B v3 (MLX) | 122 ms | 162 ms | 482 ms | 7.4% | 2.8 GB |

Word errors are over the 4 usable voice clips (81 words).

- **Accuracy:** all engines transcribed the short and medium clips perfectly. On the paragraph, the three Whisper setups made the same 3 "errors" (probably my own misreadings of the prompt). Parakeet added two more ("speech to a text", "deep gram").
- **Quantized large-v3-turbo** was no faster than CPU `small` on short commands and no more accurate on these clips, so it wasn't worth it here.
- **Parakeet** was fastest, but by only ~100 ms over whisper.cpp `small`, at 3.5× the memory. That's a poor trade on an 8 GB machine.

## Results: synthetic clips (`say` voice)

The same eight prompts spoken by macOS `say`: clean, consistent audio, with every clip usable.

### All four engines (before VAD)

| Engine | Short commands (4, mean) | Medium sentences (3, mean) | Long paragraph | Word errors | Memory |
|---|---|---|---|---|---|
| faster-whisper `small` (CPU) | 1,353 ms | 1,908 ms | 3,541 ms | 2.5% | 0.4 GB |
| **whisper.cpp `small` (Metal)** | **240 ms** | **286 ms** | **620 ms** | **1.7%** | 0.7 GB |
| whisper.cpp `large-v3-turbo-q5_0` (Metal) | 1,131 ms | 1,164 ms | 1,360 ms | 1.7% | 0.7 GB |
| Parakeet TDT 0.6B v3 (MLX) | 109 ms | 168 ms | 623 ms | 4.2% | 3.1 GB |

Word errors are over 118 words. Every error from every engine was a sound-alike: "daemon" → "demon" (all four engines), "layer" → "layers", "Deepgram" → "deep gram", "caller" → "colour" (Parakeet).

### faster-whisper vs whisper.cpp (after VAD)

| Clip type | faster-whisper | whisper.cpp `small` | Speedup |
|---|---|---|---|
| Short commands (4 clips, mean) | 1,144 ms | 242 ms | 4.7× |
| Medium sentences (3 clips, mean) | 1,247 ms | 294 ms | 4.2× |
| Long paragraph | 1,926 ms | 653 ms | 2.9× |

Note the CPU engine's variance again. The same synthetic clips took 1,353 / 1,908 / 3,541 ms in the earlier run and 1,144 / 1,247 / 1,926 ms here. whisper.cpp's numbers barely moved (240 → 242, 286 → 294, 620 → 653 ms).

## Why it's faster

- **Fixed 30-second window:** Whisper's encoder always processes a 30-second window, padding short clips with silence. A 2-second command costs nearly as much encoder work as a 25-second paragraph.
- **That fixed cost is the ~1 s floor:** on the CPU, the window takes most of a second, which is why every command felt slow.
- **The GPU shrinks it:** whisper.cpp runs the same computation on the M3's GPU, cutting that floor to about 0.2 s.
- **The rest scales with words:** the decoder, which writes out the text, takes longer the more you say, so longer clips grow from there.

## Silent presses

With auto-submit on, any text produced on a silent press gets sent to Claude as a prompt, so every engine was checked on silence. Two silent clips were used: 2 s of digital silence (synthetic) and 1 s of real room silence from my mic.

| Engine | Digital silence | Room silence (my mic) | Time spent |
|---|---|---|---|
| faster-whisper `small` | nothing ✅ | nothing ✅ | ~2–4 ms (its built-in VAD skips the model) |
| whisper.cpp `small`, no VAD | `[BLANK_AUDIO]` ❌ | `[BLANK_AUDIO]` ❌ | ~230 ms |
| whisper.cpp turbo, no VAD | "Thank you" ❌ | "Thank you" ❌ | ~1,100 ms |
| Parakeet, no VAD | nothing ✅ | "Thank you" ❌ | ~110–130 ms |
| **whisper.cpp `small` + VAD (shipped)** | **nothing ✅** | **nothing ✅** | **~2 ms** |
| whisper.cpp turbo + VAD | nothing ✅ | nothing ✅ | ~3 ms |

- **The fix:** with the silero VAD in front, a silent press returns nothing in a few milliseconds, because Whisper never runs. Speech clips gained no measurable latency from it.
- **Not a Whisper-only problem:** Parakeet is often described as not hallucinating the way Whisper does. It passed on digital silence but produced "Thank you" from real room noise. It wasn't retested with the VAD, because the VAD gate was only added to the whisper.cpp provider. Parakeet would need the same gate before it could be a safe default.

## Live preview cost

A later change shows the transcript live while the key is held, by re-running whisper.cpp on the audio so far about once a second. Final-text latency after release, streaming recorded clips in real time:

| Clip | Without preview | With preview |
|---|---|---|
| Short (2.6 s) | ~240 ms | 268 ms |
| Medium (4.4 s) | ~290 ms | 417 ms |
| Long (19.8 s) | ~600 ms | 637 ms |

- **Where the extra time comes from:** cancelling a preview run that's still in progress when you release the key.
- **Why it can't be instant:** whisper.cpp's abort callback stops a run between steps, but the encoder pass (~200 ms) can't be interrupted partway through on Metal.

## Dead end: shrinking the audio window

whisper.cpp's `audio_ctx` setting shrinks the 30-second window to fit the clip, which in theory removes the padding cost. With `large-v3-turbo` it produced garbage instead: word error rate jumped from 1.7% to 74%, with repetition loops like "of the of the of the…". One run got stuck long enough to hit a one-hour timeout. The option was removed.

## Considered but not benchmarked

These came up while choosing an engine but were **not measured**, so there are no numbers for them here. The notes are reasoning, not results.

| Option | What it is | Why it wasn't tested |
|---|---|---|
| MLX Whisper (`mlx-whisper`) | The same Whisper models on the Apple GPU through Apple's MLX library | Likely similar speed to whisper.cpp, since both run Whisper on the GPU. whisper.cpp was chosen for its maturity and ready-made quantized models. |
| whisper.cpp + Core ML | Runs Whisper's encoder on the Neural Engine instead of the GPU | The pywhispercpp wheel is built without Core ML (its system info reports `COREML = 0`). It would need a custom build plus a converted encoder model. |
| Moonshine | A small, fast model built for short on-device clips; it doesn't pad to a 30 s window | English-focused, and reported to be less accurate on long dictation. whisper.cpp `small` was already fast enough. |
| sherpa-onnx streaming Zipformer | A true streaming model with very low CPU use | Noticeably less accurate. Its main draw was live text, which the live preview now provides with Whisper. |
| Deepgram (cloud) | Already a supported provider (`nova-2`), with a live streaming mode | Latency depends on the network, and the audio leaves the machine. Out of scope for a local-engine comparison. |
| Streaming Whisper wrappers (whisper_streaming, WhisperLive) | Re-run Whisper on a sliding window to fake streaming | Rejected on design grounds: repeated compute and text that revises itself. The live preview uses the same re-run idea, but only for display. |

## Caveats

- **Small sample:** 4 usable voice clips and 8 synthetic ones. Plenty to see a consistent 4× gap, not enough for confidence intervals.
- **Some recordings were unusable:** 4 of 9 voice clips were cut off by a recording mishap and are excluded from the voice results.
- **Transcription time only:** pasting into the terminal adds a little for both engines.
- **One machine:** an M3 with 8 GB. Results on other Apple Silicon chips should be similar in shape; Intel Macs don't get the Metal path.

## Reproduce

```bash
python scripts/bench_stt.py record ~/stt-clips        # record your own clips
python scripts/bench_stt.py make-samples ~/stt-synth  # or generate synthetic ones
python scripts/bench_stt.py run ~/stt-clips --json results.json
```
