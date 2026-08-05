from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
from claude_voice.config import Config
from claude_voice.hotkey import HotkeyEvent
from claude_voice.daemon import DaemonCore


def _fake_audio(seconds: float = 1.0) -> tuple[np.ndarray, int]:
    return (np.zeros(int(seconds * 16000), dtype=np.float32), 16000)


def _mk_core():
    recorder = MagicMock()
    hotkey = MagicMock()
    stt = MagicMock()
    playback = MagicMock()
    ipc = MagicMock()
    injector = MagicMock()
    core = DaemonCore(
        config=Config(),
        recorder=recorder,
        hotkey_listener=hotkey,
        stt=stt,
        playback=playback,
        ipc=ipc,
        inject_fn=injector,
        on_state_change=lambda s: None,
        dispatch=lambda fn, args: fn(*args),  # synchronous for tests
    )
    return core, recorder, hotkey, stt, playback, ipc, injector


def test_ptt_down_starts_recording_and_interrupts_tts():
    core, recorder, _, _, playback, _, _ = _mk_core()
    playback.is_playing.return_value = True
    core.handle_hotkey(HotkeyEvent.PTT_DOWN)
    playback.interrupt.assert_called_once()
    recorder.start.assert_called_once()


def test_ptt_up_transcribes_and_injects():
    core, recorder, _, stt, _, _, injector = _mk_core()
    audio = _fake_audio()
    recorder.stop.return_value = audio
    stt.transcribe_audio.return_value = "hello world"
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    stt.transcribe_audio.assert_called_once()
    injector.assert_called_once_with("hello world")


def test_ptt_up_short_recording_no_inject():
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = None  # too short
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    stt.transcribe_audio.assert_not_called()
    injector.assert_not_called()


def test_ptt_up_empty_transcript_no_inject():
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = ""
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    injector.assert_not_called()


def test_ptt_up_while_busy_is_ignored():
    """Overlapping PTT press during transcription plays busy-tick, no new STT."""
    core, recorder, _, stt, _, _, _ = _mk_core()
    # Make STT block so the first PTT_UP stays "busy"
    from threading import Event
    proceed = Event()
    stt.transcribe_audio.side_effect = lambda a, sr: (proceed.wait(0.5), "hi")[1]
    recorder.stop.return_value = _fake_audio()

    # Use an async dispatch so the first job is still in-flight
    import threading
    core._dispatch = lambda fn, args: threading.Thread(
        target=fn, args=args, daemon=True
    ).start()

    core.handle_hotkey(HotkeyEvent.PTT_UP)
    # second press while first is running
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    proceed.set()
    # Only one transcribe call should have started
    import time; time.sleep(0.6)
    assert stt.transcribe_audio.call_count == 1


def test_speak_handler_calls_playback():
    core, _, _, _, playback, _, _ = _mk_core()
    reply = core.handle_speak({"op": "speak", "text": "hi", "response_id": "r1"})
    playback.speak.assert_called_once_with("hi", "r1")
    assert reply["ok"] is True


def test_speak_handler_deduplicates():
    core, _, _, _, playback, _, _ = _mk_core()
    core.handle_speak({"op": "speak", "text": "hi", "response_id": "r1"})
    core.handle_speak({"op": "speak", "text": "hi", "response_id": "r1"})
    assert playback.speak.call_count == 1


def test_replay_handler_calls_playback():
    core, _, _, _, playback, _, _ = _mk_core()
    playback.replay_last.return_value = True
    reply = core.handle_replay({"op": "replay"})
    assert reply["ok"] is True
    playback.replay_last.assert_called_once()
