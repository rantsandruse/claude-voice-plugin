from __future__ import annotations
from pathlib import Path
from typing import Callable
import threading
import subprocess
import sys

import rumps

from .config import Config, CONFIG_DIR, load_config, load_dotenv_if_present, secrets as read_secrets
from .hotkey import HotkeyListener, HotkeyEvent
from .recorder import Recorder
from .playback import PlaybackController
from .ipc import IPCServer, SOCKET_PATH
from .inject import inject
from .stt.whisper_local import WhisperLocalProvider
from .stt.deepgram import DeepgramProvider
from .tts.say import SayProvider
from .tts.elevenlabs import ElevenLabsProvider


def _make_stt(config: Config, secrets: dict[str, str | None]):
    if config.stt.provider == "deepgram" and secrets.get("DEEPGRAM_API_KEY"):
        return DeepgramProvider(config.stt.deepgram, secrets["DEEPGRAM_API_KEY"])
    return WhisperLocalProvider(config.stt.whisper_local)


def _make_tts_primary(config: Config, secrets: dict[str, str | None]):
    if config.tts.provider == "elevenlabs" and secrets.get("ELEVENLABS_API_KEY"):
        return ElevenLabsProvider(config.tts.elevenlabs, secrets["ELEVENLABS_API_KEY"])
    return SayProvider(config.tts.say)


def _default_dispatch(fn: Callable, args: tuple) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


class DaemonCore:
    """Non-UI wiring; VoiceDaemon adds the menu-bar shell."""
    def __init__(
        self,
        config: Config,
        recorder: Recorder,
        hotkey_listener: HotkeyListener,
        stt,
        playback: PlaybackController,
        ipc: IPCServer,
        inject_fn: Callable[[str], None],
        on_state_change: Callable[[str], None],
        dispatch: Callable[[Callable, tuple], None] | None = None,
    ):
        self._config = config
        self._recorder = recorder
        self._hotkey = hotkey_listener
        self._stt = stt
        self._playback = playback
        self._ipc = ipc
        self._inject = inject_fn
        self._on_state_change = on_state_change
        self._dispatch = dispatch or _default_dispatch
        self._last_spoken_response_id: str | None = None
        self._busy = False
        self._lock = threading.Lock()

    def start(self) -> None:
        self._hotkey.start()
        self._ipc.start()
        self._on_state_change("idle")

    def stop(self) -> None:
        self._hotkey.stop()
        self._ipc.stop()

    def handle_hotkey(self, event: HotkeyEvent) -> None:
        if event == HotkeyEvent.PTT_DOWN:
            if self._playback.is_playing():
                self._playback.interrupt()
            self._recorder.start()
            self._on_state_change("recording")
            self._play_tick("start")
        elif event == HotkeyEvent.PTT_UP:
            with self._lock:
                if self._busy:
                    self._play_tick("busy")
                    return
            wav = self._recorder.stop()
            if wav is None:
                self._on_state_change("idle")
                return
            with self._lock:
                self._busy = True
            self._on_state_change("transcribing")
            self._dispatch(self.run_transcribe_job, (wav,))

    def run_transcribe_job(self, wav: Path) -> None:
        try:
            try:
                text = self._stt.transcribe(wav)
            except Exception as e:
                print(f"[daemon] STT error: {e}", file=sys.stderr)
                self._on_state_change("error")
                return
            if not text:
                self._on_state_change("idle")
                return
            self._inject(text)
            self._play_tick("stop")
            self._on_state_change("idle")
        finally:
            with self._lock:
                self._busy = False

    def _play_tick(self, kind: str) -> None:
        if not self._config.feedback.sounds:
            return
        # macOS built-in system sounds
        sound = {"start": "Tink", "stop": "Pop", "busy": "Funk"}.get(kind, "Tink")
        try:
            subprocess.Popen(
                ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # IPC handlers
    def handle_speak(self, msg: dict) -> dict:
        if not self._config.tts.enabled:
            return {"ok": True, "skipped": "tts disabled"}
        text = msg.get("text", "")
        response_id = msg.get("response_id", "")
        if not text:
            return {"ok": True, "skipped": "empty"}
        with self._lock:
            if response_id and response_id == self._last_spoken_response_id:
                return {"ok": True, "skipped": "duplicate"}
            self._last_spoken_response_id = response_id
        self._playback.speak(text, response_id)
        self._on_state_change("playing")
        return {"ok": True}

    def handle_replay(self, _msg: dict) -> dict:
        ok = self._playback.replay_last()
        if ok:
            self._on_state_change("playing")
        return {"ok": ok}

    def handle_status(self, _msg: dict) -> dict:
        return {
            "ok": True,
            "playing": self._playback.is_playing(),
            "stt_provider": type(self._stt).__name__,
        }

    def handle_interrupt(self, _msg: dict) -> dict:
        self._playback.interrupt()
        self._on_state_change("idle")
        return {"ok": True}


_STATE_ICONS = {
    "idle": "🎙️",
    "recording": "🔴",
    "transcribing": "⏳",
    "playing": "🔊",
    "error": "⚠️",
}


class VoiceDaemon(rumps.App):
    def __init__(self, config: Config, secrets: dict[str, str | None]):
        # Force menu-bar accessory mode BEFORE rumps registers its status item,
        # so the icon persists reliably when run from a plain venv Python
        # (no .app bundle, no Dock entry).
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)
        except Exception:
            pass
        super().__init__("Claude Voice", title="🎙️")
        self._config = config

        stt = _make_stt(config, secrets)
        primary_tts = _make_tts_primary(config, secrets)
        fallback_tts = SayProvider(config.tts.say)
        playback = PlaybackController(primary_tts, fallback=fallback_tts)
        recorder = Recorder()
        hotkey_listener = HotkeyListener(config.hotkey, on_event=self._on_hotkey)

        # Handlers dict is mutated after DaemonCore exists (they close over self._core)
        handlers: dict = {}
        ipc = IPCServer(SOCKET_PATH, handlers)

        self._core = DaemonCore(
            config=config,
            recorder=recorder,
            hotkey_listener=hotkey_listener,
            stt=stt,
            playback=playback,
            ipc=ipc,
            inject_fn=lambda text: inject(text, auto_submit=config.inject.auto_submit),
            on_state_change=self._on_state_change,
        )
        handlers["speak"] = self._core.handle_speak
        handlers["replay"] = self._core.handle_replay
        handlers["status"] = self._core.handle_status
        handlers["interrupt"] = self._core.handle_interrupt

        def _quit_handler(_m: dict) -> dict:
            rumps.quit_application()
            return {"ok": True}
        handlers["quit"] = _quit_handler

        # menu
        self.menu = [
            rumps.MenuItem("Replay last", callback=self._menu_replay),
            rumps.MenuItem("Edit config…", callback=self._menu_edit_config),
        ]

    def _on_hotkey(self, event: HotkeyEvent) -> None:
        self._core.handle_hotkey(event)

    def _on_state_change(self, state: str) -> None:
        self.title = _STATE_ICONS.get(state, "🎙️")

    def _menu_replay(self, _sender) -> None:
        self._core.handle_replay({})

    def _menu_edit_config(self, _sender) -> None:
        subprocess.Popen(["open", str(CONFIG_DIR / "config.yaml")])

    def run(self) -> None:
        self._core.start()
        super().run()


def run_daemon() -> None:
    load_dotenv_if_present()
    config = load_config()
    secrets = read_secrets()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    daemon = VoiceDaemon(config, secrets)

    # Ensure clean shutdown on Ctrl+C / SIGTERM:
    # - unlinks the daemon.sock file (otherwise blocks next start)
    # - stops the pynput listener (silences leaked-semaphore warnings)
    # - lets rumps quit its main loop gracefully
    import signal

    def _shutdown(*_):
        try:
            daemon._core.stop()
        except Exception:
            pass
        rumps.quit_application()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    daemon.run()
