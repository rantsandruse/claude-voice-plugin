from __future__ import annotations
import subprocess
import threading
import sys
from .tts.base import TTSProvider


class PlaybackController:
    def __init__(self, provider: TTSProvider, fallback: TTSProvider | None = None):
        self._provider = provider
        self._fallback = fallback
        self._current: subprocess.Popen | None = None
        self._last: tuple[str, str] | None = None  # (response_id, text)
        self._lock = threading.Lock()

    def speak(self, text: str, response_id: str) -> bool:
        self.interrupt()
        with self._lock:
            handle: subprocess.Popen | None = None
            try:
                handle = self._provider.speak(text)
            except Exception as e:
                print(f"[playback] primary TTS failed: {e}", file=sys.stderr)
                if self._fallback is not None:
                    try:
                        handle = self._fallback.speak(text)
                    except Exception as e2:
                        print(f"[playback] fallback also failed: {e2}", file=sys.stderr)
                        handle = None
            if handle is None:
                return False
            self._current = handle
            self._last = (response_id, text)
            return True

    def interrupt(self) -> None:
        with self._lock:
            if self._current is not None and self._current.poll() is None:
                try:
                    self._current.terminate()
                except Exception:
                    pass
            self._current = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._current is not None and self._current.poll() is None

    def replay_last(self) -> bool:
        with self._lock:
            last = self._last
        if last is None:
            return False
        return self.speak(last[1], last[0])
