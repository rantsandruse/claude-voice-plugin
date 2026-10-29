from __future__ import annotations
from typing import Callable
import threading
import time
import numpy as np

SAMPLE_RATE = 16000

# (start_s, end_s) of each speech region in a clip.
SpeechFn = Callable[[np.ndarray], list[tuple[float, float]]]


def silero_speech(audio: np.ndarray) -> list[tuple[float, float]]:
    """Speech regions via the silero VAD bundled with faster-whisper.
    No padding and a short min-silence, so a region ends where speech ends
    rather than where faster-whisper's transcription defaults would."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(min_speech_duration_ms=250, min_silence_duration_ms=100, speech_pad_ms=0)
    return [
        (t["start"] / SAMPLE_RATE, t["end"] / SAMPLE_RATE)
        for t in get_speech_timestamps(audio, opts)
    ]


class EndpointDetector:
    """Watches a recording in progress and calls on_end(reason) once:

    - "silence":   speech happened and has been followed by silence_s of quiet
    - "no_speech": nothing was said within no_speech_timeout_s
    - "max":       speech has gone on for max_s (timed from when it began,
                   so a long wait for speech doesn't eat into it)

    Only the last silence_s + 1 s is checked on each tick, so the cost stays
    flat however long the dictation runs.
    """

    def __init__(
        self,
        snapshot: Callable[[], np.ndarray | None],
        on_end: Callable[[str], None],
        silence_s: float = 1.2,
        no_speech_timeout_s: float = 5.0,
        max_s: float = 60.0,
        interval: float = 0.2,
        speech: SpeechFn = silero_speech,
    ):
        self._snapshot = snapshot
        self._on_end = on_end
        self._silence_s = silence_s
        self._no_speech_timeout_s = no_speech_timeout_s
        self._max_s = max_s
        self._interval = interval
        self._speech = speech
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # on_end may call stop() from the detector's own thread.
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self, stop: threading.Event) -> None:
        reason = self._watch(stop)
        if reason is not None and not stop.is_set():
            self._on_end(reason)

    def _watch(self, stop: threading.Event) -> str | None:
        window_samples = int((self._silence_s + 1.0) * SAMPLE_RATE)
        first_speech_start: float | None = None
        last_speech_end: float | None = None
        started = time.monotonic()
        while not stop.wait(self._interval):
            audio = self._snapshot()
            if audio is None:
                # No audio at all (e.g. the mic stopped delivering): fall back
                # to wall-clock time so the no-speech timeout still fires.
                if time.monotonic() - started >= self._no_speech_timeout_s:
                    return "no_speech"
                continue
            now = len(audio) / SAMPLE_RATE
            if first_speech_start is not None and now - first_speech_start >= self._max_s:
                return "max"
            window = audio[-window_samples:]
            offset = now - len(window) / SAMPLE_RATE
            regions = self._speech(window)
            if regions:
                if first_speech_start is None:
                    first_speech_start = offset + regions[0][0]
                last_speech_end = offset + regions[-1][1]
            if last_speech_end is None:
                if now >= self._no_speech_timeout_s:
                    return "no_speech"
                continue
            if now - last_speech_end >= self._silence_s:
                return "silence"
        return None
