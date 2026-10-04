from __future__ import annotations
from typing import Callable
import sys
import threading
import numpy as np

SAMPLE_RATE = 16000


class LivePreview:
    """While PTT is held, repeatedly transcribe the audio so far and show it.

    Display only: the text pasted on release still comes from the normal
    full-clip transcription, so the preview can never change what's sent.
    """

    def __init__(
        self,
        snapshot: Callable[[], np.ndarray | None],
        transcribe: Callable[[np.ndarray, Callable[[], bool]], str],
        show: Callable[[str], None],
        hide: Callable[[], None],
        interval: float = 0.5,
        min_audio_s: float = 0.5,
        # Whisper's window is 30 s; past that, preview just the tail rather
        # than paying for multi-window runs on every tick.
        max_audio_s: float = 28.0,
    ):
        self._snapshot = snapshot
        self._transcribe = transcribe
        self._show = show
        self._hide = hide
        self._interval = interval
        self._min_samples = int(min_audio_s * SAMPLE_RATE)
        self._max_samples = int(max_audio_s * SAMPLE_RATE)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self._stop = threading.Event()
        self._show("Listening…")
        self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Cancel any in-flight run and wait for it, so the final
        transcription doesn't queue behind a preview."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            self._hide()

    def _run(self, stop: threading.Event) -> None:
        last_len = 0
        while not stop.wait(self._interval):
            audio = self._snapshot()
            if audio is None or len(audio) < self._min_samples or len(audio) == last_len:
                continue
            last_len = len(audio)
            truncated = len(audio) > self._max_samples
            if truncated:
                audio = audio[-self._max_samples:]
            try:
                text = self._transcribe(audio, stop.is_set)
            except Exception as e:
                # Preview is a nicety; never let it break recording.
                print(f"[preview] transcribe failed, preview off for this press: {e}", file=sys.stderr)
                return
            if text and not stop.is_set():
                self._show(("…" + text) if truncated else text)
