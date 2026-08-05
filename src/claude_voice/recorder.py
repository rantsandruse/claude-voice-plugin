from __future__ import annotations
from pathlib import Path
import time
import wave
import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        output_dir: Path = Path("/tmp/claude-voice"),
    ):
        self._sample_rate = sample_rate
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._callback_ref = None  # keep a strong ref to prevent GC on audio thread
        self._active = False

    def _make_callback(self):
        """Build a plain closure over the buffer, avoiding bound-method
        indirection that has caused segfaults on macOS 14+ in the portaudio
        Core Audio callback thread."""
        buffer = self._buffer  # bind by closure, not attribute lookup
        active_check = lambda: self._active

        def _cb(indata, frames, time_info, status):
            if active_check():
                buffer.append(indata.copy())

        return _cb

    def start(self) -> None:
        self._buffer = []
        self._active = True
        self._callback_ref = self._make_callback()
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback_ref,
        )
        self._stream.start()

    def stop(self) -> Path | None:
        if not self._active or self._stream is None:
            return None
        # Mark inactive first so any in-flight callback becomes a no-op
        self._active = False
        # Give portaudio's audio thread a moment to see the flag and exit its
        # callback cleanly before we tear down the stream. Prevents cffi
        # marshaling a call into freed Python state on macOS 14+.
        time.sleep(0.05)
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._stream = None
        self._callback_ref = None
        if not self._buffer:
            return None
        audio = np.concatenate(self._buffer, axis=0)
        duration = len(audio) / self._sample_rate
        if duration < 0.3:
            return None
        path = self._output_dir / f"{int(time.time() * 1000)}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._sample_rate)
            w.writeframes(audio.tobytes())
        return path
