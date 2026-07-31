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
        self._active = False

    def _callback(self, indata, frames, time_info, status):
        if self._active:
            self._buffer.append(indata.copy())

    def start(self) -> None:
        self._buffer = []
        self._active = True
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> Path | None:
        if not self._active or self._stream is None:
            return None
        self._active = False
        self._stream.stop()
        self._stream.close()
        self._stream = None
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
