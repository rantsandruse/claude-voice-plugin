from __future__ import annotations
from pathlib import Path
import sys
import time
import wave
import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        output_dir: Path | None = None,
    ):
        self._sample_rate = sample_rate
        # output_dir is only used by the legacy stop_to_wav() path. The main
        # daemon flow now consumes audio in-memory via stop().
        self._output_dir = output_dir
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

    def _open_stream(self) -> sd.InputStream:
        return sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback_ref,
        )

    def start(self) -> None:
        self._buffer = []
        self._active = True
        self._callback_ref = self._make_callback()
        try:
            self._stream = self._open_stream()
            self._stream.start()
        except sd.PortAudioError as e:
            # PortAudio's internal Core Audio state drifts on long-running
            # daemons — device topology changes (headphones plugged in,
            # Continuity Camera in/out of range, video-call apps grabbing
            # exclusive input) accumulate until the next open fails with a
            # generic internal error. sd._terminate + sd._initialize resets
            # PortAudio's process-scoped state without needing a daemon
            # restart. If the retry also fails, the exception propagates to
            # handle_hotkey which surfaces the ⚠️ error state.
            print(f"[recorder] PortAudio error ({e}); resetting and retrying", file=sys.stderr)
            try:
                sd._terminate()
                sd._initialize()
            except Exception as reset_err:
                print(f"[recorder] PortAudio reset failed: {reset_err}", file=sys.stderr)
            self._stream = self._open_stream()
            self._stream.start()

    def stop(self) -> tuple[np.ndarray, int] | None:
        """Stop recording. Returns (float32 audio in [-1, 1], sample_rate) or
        None if the recording was too short. No disk I/O — audio is handed to
        the STT provider in memory, cutting ~50-100ms off the PTT round-trip
        and eliminating the /tmp/claude-voice/*.wav accumulation."""
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
        # int16 → float32 in [-1, 1], the format both providers accept directly.
        audio_f32 = audio.reshape(-1).astype(np.float32) / 32768.0
        return audio_f32, self._sample_rate

    def stop_to_wav(self) -> Path | None:
        """Legacy helper for the CLI test-mic command. Writes the recording
        to output_dir and returns the path. Not used in the PTT hot path."""
        result = self.stop()
        if result is None:
            return None
        audio_f32, sr = result
        out_dir = self._output_dir or Path("/tmp/claude-voice")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{int(time.time() * 1000)}.wav"
        audio_i16 = np.clip(audio_f32 * 32768.0, -32768, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(audio_i16.tobytes())
        return path
