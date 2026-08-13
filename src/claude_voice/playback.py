from __future__ import annotations
import subprocess
import threading
import sys
from .tts.base import TTSProvider


class PlaybackController:
    def __init__(
        self,
        provider: TTSProvider,
        fallback: TTSProvider | None = None,
        max_duration_seconds: float = 60.0,
    ):
        self._provider = provider
        self._fallback = fallback
        self._max_duration_seconds = max_duration_seconds
        self._current: subprocess.Popen | None = None
        # Timer that fires _watchdog_terminate() if the current subprocess
        # is still alive after max_duration_seconds. Cancelled on interrupt.
        self._watchdog: threading.Timer | None = None
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
            # Auto-kill guard: if the subprocess is still alive after
            # max_duration_seconds, terminate it. Prevents zombie say/afplay
            # from blocking future PTT presses. Daemon-thread so it doesn't
            # keep the process alive on shutdown.
            timer = threading.Timer(
                self._max_duration_seconds,
                self._watchdog_terminate,
                args=(handle,),
            )
            timer.daemon = True
            self._watchdog = timer
            timer.start()
            return True

    def _watchdog_terminate(self, handle: subprocess.Popen) -> None:
        try:
            if handle.poll() is None:
                handle.terminate()
        except Exception:
            pass

    def interrupt(self) -> None:
        # Snapshot state under the lock, then do the potentially-slow
        # terminate/wait outside so we don't hold up other callers.
        with self._lock:
            proc = self._current
            watchdog = self._watchdog
            self._current = None
            self._watchdog = None
        if watchdog is not None:
            watchdog.cancel()
        if proc is None or proc.poll() is not None:
            return
        # Robust kill: SIGTERM → short wait → SIGKILL if still alive.
        # Ensures the audio device is released before the next PTT press
        # opens an InputStream.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass  # zombie — leave it to the OS reaper
        except Exception:
            pass

    def is_playing(self) -> bool:
        with self._lock:
            return self._current is not None and self._current.poll() is None

    def replay_last(self) -> bool:
        with self._lock:
            last = self._last
        if last is None:
            return False
        return self.speak(last[1], last[0])
