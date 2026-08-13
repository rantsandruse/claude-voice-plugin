from __future__ import annotations
from pathlib import Path
from typing import Callable
import hashlib
import threading
import subprocess
import sys
import time

import rumps
from PyObjCTools.AppHelper import callAfter

from .config import Config, CONFIG_DIR, VERBATIM_FLAG_PATH, load_config, load_dotenv_if_present, secrets as read_secrets
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


def _is_verbatim_command(text: str) -> bool:
    """Standalone-word match: 'verbatim', case-insensitive, allowing common
    Whisper punctuation drift ('Verbatim.', 'verbatim,'). Only fires when the
    entire utterance is the command — 'please summarize verbatim' pastes
    normally."""
    token = text.strip().lower().rstrip(".,!?")
    return token == "verbatim"


def _set_verbatim_flag() -> None:
    """Touch the one-shot flag file the Stop hook reads."""
    try:
        VERBATIM_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        VERBATIM_FLAG_PATH.touch()
    except OSError:
        pass


def _text_key(text: str) -> str:
    """Short deterministic fingerprint for TTS dedup. Truncated SHA-1 to keep
    memory bounded across long sessions — collision-safe within a single turn's
    handful of speak calls."""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


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
        # Text fingerprint of the last spoken text. Used together with
        # response_id so a same-id message whose text has grown (streaming
        # append, resummary drift) still gets spoken instead of deduped away.
        self._last_spoken_text_key: str | None = None
        # Monotonic turn counter, incremented on each successful PTT_UP.
        # The hook snapshots this before its blocking work (Haiku summarize).
        # A speak that arrives stamped with an older generation means the
        # user has already moved to a new turn while the hook was in flight;
        # we drop it rather than speak the prior turn's response late.
        self._current_generation: int = 0
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
            # If Recorder.start() throws (PortAudio internal state gone stale,
            # mic permission revoked, device disappeared), surface it to the
            # user immediately instead of letting pynput swallow the traceback.
            try:
                self._recorder.start()
            except Exception as e:
                print(f"[daemon] recorder start failed: {e}", file=sys.stderr)
                self._on_state_change("error")
                self._play_tick("busy")
                return
            self._on_state_change("recording")
            self._play_tick("start")
        elif event == HotkeyEvent.PTT_UP:
            with self._lock:
                if self._busy:
                    self._play_tick("busy")
                    return
            try:
                audio_data = self._recorder.stop()
            except Exception as e:
                print(f"[daemon] recorder stop failed: {e}", file=sys.stderr)
                self._on_state_change("error")
                self._play_tick("busy")
                return
            if audio_data is None:
                self._on_state_change("idle")
                return
            with self._lock:
                # Bump the turn generation as soon as we have real audio for a
                # new user turn. Any in-flight hook from the previous turn will
                # have snapshotted the older generation; its late speak will be
                # dropped by handle_speak.
                self._current_generation += 1
                self._busy = True
            self._on_state_change("transcribing")
            self._dispatch(self.run_transcribe_job, (audio_data,))

    def run_transcribe_job(self, audio_data: tuple) -> None:
        audio, sample_rate = audio_data
        try:
            try:
                text = self._stt.transcribe_audio(audio, sample_rate)
            except Exception as e:
                print(f"[daemon] STT error: {e}", file=sys.stderr)
                self._on_state_change("error")
                return
            if not text:
                self._on_state_change("idle")
                return
            # Hands-free command intercept: if the user spoke just "verbatim",
            # don't paste it — set the one-shot flag so the next Stop-hook
            # response skips summarization, then bail out early.
            if _is_verbatim_command(text):
                _set_verbatim_flag()
                self._play_tick("verbatim")
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
        # macOS built-in system sounds. "verbatim" gets Glass — a bright
        # distinctive confirmation so the one-shot voice command is
        # audibly different from the routine start/stop ticks.
        sound = {
            "start": "Tink",
            "stop": "Pop",
            "busy": "Funk",
            "verbatim": "Glass",
        }.get(kind, "Tink")
        try:
            subprocess.Popen(
                ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    # IPC handlers
    def handle_generation(self, _msg: dict) -> dict:
        """Return the current turn generation. Hooks call this at start so
        their subsequent speak can be tagged with the generation they belong
        to — letting the daemon drop late-arriving speaks from prior turns."""
        with self._lock:
            return {"ok": True, "generation": self._current_generation}

    def handle_speak(self, msg: dict) -> dict:
        if not self._config.tts.enabled:
            return {"ok": True, "skipped": "tts disabled"}
        text = msg.get("text", "")
        response_id = msg.get("response_id", "")
        speak_generation = msg.get("generation")
        if not text:
            return {"ok": True, "skipped": "empty"}
        text_key = _text_key(text)
        with self._lock:
            # Stale-turn drop: hook snapshotted the generation before doing
            # blocking work (summarize / IPC). If the user has since pressed
            # PTT to start a new turn, self._current_generation has advanced.
            # Speaking now would land turn N-1's audio after the user has
            # moved to turn N — the "backlogged by one" symptom.
            if (
                isinstance(speak_generation, int)
                and speak_generation < self._current_generation
            ):
                return {"ok": True, "skipped": "stale generation"}
            # Dedup on the (id, text) pair: same id + same text = already
            # spoken. If the text changed for the same id (e.g. Stop reads
            # a longer version, or resummarization produces a new string),
            # treat it as a new utterance and speak it.
            if (
                response_id
                and response_id == self._last_spoken_response_id
                and text_key == self._last_spoken_text_key
            ):
                return {"ok": True, "skipped": "duplicate"}
            self._last_spoken_response_id = response_id
            self._last_spoken_text_key = text_key
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
        # Preload weights so the first PTT press doesn't eat the cold-load
        # penalty. No-op for Deepgram. Failure isn't fatal — fall back to
        # lazy-load on first press.
        warmup = getattr(stt, "warmup", None)
        if callable(warmup):
            print("[daemon] preloading STT model…", file=sys.stderr)
            try:
                warmup()
            except Exception as e:
                print(f"[daemon] STT warmup failed: {e}", file=sys.stderr)
        primary_tts = _make_tts_primary(config, secrets)
        fallback_tts = SayProvider(config.tts.say)
        playback = PlaybackController(
            primary_tts,
            fallback=fallback_tts,
            max_duration_seconds=float(config.tts.max_duration),
        )
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
        handlers["generation"] = self._core.handle_generation

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
        # Assigning self.title reaches into NSStatusItem/Core Animation, which
        # is main-thread-only. This method is invoked from the IPC thread and
        # from the transcribe worker; setting the title directly from those
        # threads segfaults on pthread teardown (QuartzCore CA::Transaction).
        icon = _STATE_ICONS.get(state, "🎙️")
        callAfter(lambda: setattr(self, "title", icon))

    def _menu_replay(self, _sender) -> None:
        self._core.handle_replay({})

    def _menu_edit_config(self, _sender) -> None:
        subprocess.Popen(["open", str(CONFIG_DIR / "config.yaml")])

    def run(self) -> None:
        self._core.start()
        super().run()


def _purge_old_wavs(directory: Path = Path("/tmp/claude-voice"), older_than_hours: float = 24) -> None:
    """Sweep stale PTT recordings left by prior daemon crashes. macOS reaps
    /tmp on a 3-day schedule; we tighten that to a day for a smaller privacy
    window on unencrypted speech audio."""
    if not directory.exists():
        return
    cutoff = time.time() - older_than_hours * 3600
    for wav in directory.glob("*.wav"):
        try:
            if wav.stat().st_mtime < cutoff:
                wav.unlink()
        except OSError:
            pass


def run_daemon() -> None:
    load_dotenv_if_present()
    config = load_config()
    secrets = read_secrets()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _purge_old_wavs()

    # Clean stale socket from a previously-crashed daemon so this start
    # succeeds cleanly. IPCServer.start() also does this, but doing it
    # early gives a clearer failure signal if permissions are wrong.
    try:
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
    except OSError:
        pass

    daemon = VoiceDaemon(config, secrets)

    # Best-effort cleanup at interpreter shutdown. Runs AFTER rumps'
    # event loop returns, so it doesn't race with AppKit like a
    # signal-handler-driven quit would.
    import atexit

    def _cleanup():
        try:
            daemon._core.stop()
        except Exception:
            pass

    atexit.register(_cleanup)
    daemon.run()
