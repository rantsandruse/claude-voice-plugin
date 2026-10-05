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


def test_speak_handler_same_id_different_text_speaks():
    """Same response_id with different text (e.g., Stop reads a longer version
    of the message that PreToolUse spoke earlier as a preamble) must not be
    deduped away — otherwise the final answer is silently swallowed."""
    core, _, _, _, playback, _, _ = _mk_core()
    core.handle_speak({"op": "speak", "text": "let me look", "response_id": "r1"})
    core.handle_speak({"op": "speak", "text": "here is the answer", "response_id": "r1"})
    assert playback.speak.call_count == 2
    assert playback.speak.call_args_list[1].args == ("here is the answer", "r1")


def test_speak_handler_dedupes_same_id_same_text():
    """Byte-identical repeats (Stop firing after PreToolUse for the same
    unchanged text) still get deduped."""
    core, _, _, _, playback, _, _ = _mk_core()
    core.handle_speak({"op": "speak", "text": "same text", "response_id": "r1"})
    core.handle_speak({"op": "speak", "text": "same text", "response_id": "r1"})
    assert playback.speak.call_count == 1


def test_generation_starts_at_zero():
    core, _, _, _, _, _, _ = _mk_core()
    assert core.handle_generation({})["generation"] == 0


def test_generation_increments_on_committed_turn():
    """A committed turn = audio captured + transcription non-empty + not the
    hands-free 'verbatim' command. Only then does the user actually own a new
    turn, so only then should gen advance."""
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "hello"
    assert core.handle_generation({})["generation"] == 0
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert core.handle_generation({})["generation"] == 1
    injector.assert_called_once_with("hello")
    # Second successful PTT: gen == 2.
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert core.handle_generation({})["generation"] == 2


def test_generation_does_not_increment_when_recording_too_short():
    """Zero-audio PTT is not a real turn — no generation bump."""
    core, recorder, _, _, _, _, _ = _mk_core()
    recorder.stop.return_value = None
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert core.handle_generation({})["generation"] == 0


def test_generation_does_not_increment_on_empty_transcription():
    """PTT captured audio but Whisper returned empty — the user didn't commit
    a turn. Bumping here would drop legitimate speaks from the prior turn."""
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = ""
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert core.handle_generation({})["generation"] == 0
    injector.assert_not_called()


def test_generation_does_not_increment_on_verbatim_command(tmp_path, mocker):
    """The 'verbatim' hands-free command tweaks the NEXT response's mode; it
    is not itself a new turn, so gen must not advance."""
    flag_path = tmp_path / "next-verbatim.flag"
    mocker.patch("claude_voice.daemon.VERBATIM_FLAG_PATH", flag_path)
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "verbatim"
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert core.handle_generation({})["generation"] == 0
    injector.assert_not_called()
    assert flag_path.exists()


def test_speak_dropped_when_generation_is_stale():
    """The core scenario the fix addresses: hook snapshotted generation N,
    user PTT'd during hook's summarize, daemon advanced to N+1. When the
    late speak arrives, it must not play."""
    core, recorder, _, stt, playback, _, _ = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "next turn"
    # Simulate a hook that snapshotted generation=0 at the start.
    snapshot = core.handle_generation({})["generation"]
    # User PTT for a new turn while the hook is still summarizing — daemon
    # generation advances to 1.
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    # The stale hook finally sends its speak.
    reply = core.handle_speak({
        "op": "speak",
        "text": "prior turn's answer",
        "response_id": "old",
        "generation": snapshot,
    })
    assert reply["skipped"] == "stale generation"
    playback.speak.assert_not_called()


def test_speak_plays_when_generation_matches_current():
    core, _, _, _, playback, _, _ = _mk_core()
    reply = core.handle_speak({
        "op": "speak",
        "text": "hi",
        "response_id": "r1",
        "generation": 0,
    })
    assert reply["ok"] is True
    playback.speak.assert_called_once_with("hi", "r1")


def test_speak_plays_when_generation_omitted_backcompat():
    """A hook that predates the generation protocol still works — no drop."""
    core, _, _, _, playback, _, _ = _mk_core()
    reply = core.handle_speak({"op": "speak", "text": "hi", "response_id": "r1"})
    assert reply["ok"] is True
    playback.speak.assert_called_once_with("hi", "r1")


def test_replay_handler_calls_playback():
    core, _, _, _, playback, _, _ = _mk_core()
    playback.replay_last.return_value = True
    reply = core.handle_replay({"op": "replay"})
    assert reply["ok"] is True
    playback.replay_last.assert_called_once()


def test_verbatim_command_sets_flag_and_skips_inject(tmp_path, mocker):
    """When the user speaks only 'verbatim', the daemon touches the one-shot
    flag file and does NOT paste the word into the terminal."""
    flag_path = tmp_path / "next-verbatim.flag"
    mocker.patch("claude_voice.daemon.VERBATIM_FLAG_PATH", flag_path)

    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "verbatim"

    core.handle_hotkey(HotkeyEvent.PTT_UP)

    injector.assert_not_called()
    assert flag_path.exists()


def test_verbatim_case_insensitive_and_punctuation_tolerant(tmp_path, mocker):
    """Whisper often returns 'Verbatim.' with a trailing period; still counts."""
    flag_path = tmp_path / "next-verbatim.flag"
    mocker.patch("claude_voice.daemon.VERBATIM_FLAG_PATH", flag_path)

    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "Verbatim."

    core.handle_hotkey(HotkeyEvent.PTT_UP)

    injector.assert_not_called()
    assert flag_path.exists()


def test_verbatim_only_matches_standalone_word(tmp_path, mocker):
    """'please summarize verbatim' should paste, not toggle the flag."""
    flag_path = tmp_path / "next-verbatim.flag"
    mocker.patch("claude_voice.daemon.VERBATIM_FLAG_PATH", flag_path)

    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = _fake_audio()
    stt.transcribe_audio.return_value = "please summarize verbatim"

    core.handle_hotkey(HotkeyEvent.PTT_UP)

    injector.assert_called_once_with("please summarize verbatim")
    assert not flag_path.exists()


def test_make_stt_selects_optional_local_backends():
    from claude_voice.config import Config, STTConfig
    from claude_voice.daemon import _make_stt
    from claude_voice.stt.parakeet import ParakeetProvider
    from claude_voice.stt.whisper_cpp import WhisperCppProvider

    # Constructing providers is lazy (no model load), so this stays fast.
    assert isinstance(_make_stt(Config(stt=STTConfig(provider="whisper_cpp")), {}), WhisperCppProvider)
    assert isinstance(_make_stt(Config(stt=STTConfig(provider="parakeet")), {}), ParakeetProvider)


def test_make_stt_falls_back_when_whisper_cpp_missing(mocker):
    from claude_voice.config import Config
    from claude_voice.daemon import _make_stt
    from claude_voice.stt.whisper_local import WhisperLocalProvider

    mocker.patch("claude_voice.daemon.importlib.util.find_spec", return_value=None)
    assert isinstance(_make_stt(Config(), {}), WhisperLocalProvider)


def _run_redirect_in_subprocess(log_path, stderr):
    # dup2 rewires the process's real stdout/stderr, so exercise it in a
    # child rather than hijacking pytest's own output.
    import subprocess, sys
    code = (
        "import sys; from pathlib import Path;"
        "from claude_voice.daemon import _redirect_output_to_log;"
        f"_redirect_output_to_log(Path({str(log_path)!r}));"
        "print('[daemon] hello', file=sys.stderr); print('out line')"
    )
    return subprocess.run([sys.executable, "-c", code], stderr=stderr, stdout=stderr,
                          stdin=subprocess.DEVNULL, timeout=60)


def test_output_goes_to_log_when_started_without_terminal(tmp_path):
    import subprocess
    log = tmp_path / "logs" / "daemon.log"
    _run_redirect_in_subprocess(log, subprocess.DEVNULL)
    text = log.read_text()
    assert "--- started" in text
    assert "[daemon] hello" in text
    assert "out line" in text


def test_oversized_log_is_rotated(tmp_path):
    import subprocess
    from claude_voice.daemon import _LOG_MAX_BYTES
    log = tmp_path / "daemon.log"
    log.write_bytes(b"x" * (_LOG_MAX_BYTES + 1))
    _run_redirect_in_subprocess(log, subprocess.DEVNULL)
    assert (tmp_path / "daemon.log.1").stat().st_size == _LOG_MAX_BYTES + 1
    assert "[daemon] hello" in log.read_text()


def _mk_core_with_preview():
    from unittest.mock import MagicMock
    core, recorder, hotkey, stt, playback, ipc, injector = _mk_core()
    preview = MagicMock()
    core._preview = preview
    return core, recorder, stt, preview


def test_preview_starts_on_press_and_stops_before_final_transcription():
    core, recorder, stt, preview = _mk_core_with_preview()
    order = []
    preview.stop.side_effect = lambda: order.append("preview.stop")

    def stop_recorder():
        order.append("recorder.stop")
        return _fake_audio()

    recorder.stop.side_effect = stop_recorder
    stt.transcribe_audio.return_value = "hello"
    core.handle_hotkey(HotkeyEvent.PTT_DOWN)
    preview.start.assert_called_once()
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    assert order == ["preview.stop", "recorder.stop"]


def test_preview_not_started_when_recorder_fails():
    core, recorder, _, preview = _mk_core_with_preview()
    recorder.start.side_effect = RuntimeError("mic gone")
    core.handle_hotkey(HotkeyEvent.PTT_DOWN)
    preview.start.assert_not_called()


def test_rewordings_of_same_source_text_are_spoken_once():
    """The reported bug: one response, summarized differently per PreToolUse,
    was spoken five times, each cutting off the last."""
    core, _, _, _, playback, _, _ = _mk_core()
    for wording in ["first wording", "second wording", "third wording"]:
        core.handle_speak({"op": "speak", "text": wording, "response_id": "m1", "source_key": "abc"})
    assert playback.speak.call_count == 1


def test_out_of_order_repeat_of_earlier_text_is_dropped():
    core, _, _, _, playback, _, _ = _mk_core()
    for key in ["a", "b", "a"]:
        core.handle_speak({"op": "speak", "text": f"text {key}", "response_id": key, "source_key": key})
    assert [c.args[0] for c in playback.speak.call_args_list] == ["text a", "text b"]


def test_generation_reports_whether_source_text_was_spoken():
    core, *_ = _mk_core()
    assert core.handle_generation({"source_key": "abc"})["spoken"] is False
    core.handle_speak({"op": "speak", "text": "hi", "response_id": "m1", "source_key": "abc"})
    assert core.handle_generation({"source_key": "abc"})["spoken"] is True
    assert core.handle_generation({})["spoken"] is False


def test_new_turn_allows_same_text_again():
    core, _, _, _, playback, _, _ = _mk_core()
    msg = {"op": "speak", "text": "Done.", "response_id": "m1", "source_key": "abc"}
    core.handle_speak(msg)
    core.handle_new_turn({})
    core.handle_speak(dict(msg, response_id="m2"))
    assert playback.speak.call_count == 2


def test_new_turn_clears_queued_speech():
    core, _, _, _, playback, _, _ = _mk_core()
    core.handle_new_turn({})
    playback.clear_queue.assert_called_once()
    playback.interrupt.assert_not_called()
