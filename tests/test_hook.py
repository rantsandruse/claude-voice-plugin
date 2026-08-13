import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from claude_voice.hook import main
from claude_voice.config import Config, FeedbackConfig


def _run_with_stdin(payload: dict, mocker) -> int:
    mocker.patch("sys.stdin", io.StringIO(json.dumps(payload)))
    return main()


def test_no_transcript_path_returns_0(mocker):
    assert _run_with_stdin({"hook_event_name": "Stop"}, mocker) == 0


def test_missing_file_returns_0(mocker):
    assert _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": "/nonexistent.jsonl"},
        mocker,
    ) == 0


def test_sends_speak_message(tmp_path, mocker):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"Hello there."}]}}\n'
    )
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": None},
    )
    rc = _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )
    assert rc == 0
    assert send.called
    msg = send.call_args.args[0]
    assert msg["op"] == "speak"
    assert msg["response_id"] == "m1"
    assert "Hello there" in msg["text"]


def test_empty_cleaned_text_skips_send(tmp_path, mocker):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"```py\\nx=1\\n```"}]}}\n'
    )
    send = mocker.patch("claude_voice.hook.send_message")
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": None},
    )
    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )
    send.assert_not_called()


def test_summarize_used_for_long_response(tmp_path, mocker):
    long_text = "Long prose. " * 500  # >> 500 chars
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        json.dumps({
            "type": "assistant",
            "message": {"id": "m2", "role": "assistant",
                        "content": [{"type": "text", "text": long_text}]},
        }) + "\n"
    )
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": "k"},
    )
    summarize = mocker.patch(
        "claude_voice.hook.summarize", return_value="short summary"
    )
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )
    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )
    summarize.assert_called_once()
    assert send.call_args.args[0]["text"] == "short summary"


def test_userpromptsubmit_plays_tick_and_skips_speak(mocker):
    """A′: On UserPromptSubmit, tick and exit without touching TTS."""
    tick = mocker.patch("claude_voice.hook._play_tick")
    send = mocker.patch("claude_voice.hook.send_message")
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    _run_with_stdin({"hook_event_name": "UserPromptSubmit"}, mocker)
    tick.assert_called_once_with("Ping")
    send.assert_not_called()


def test_userpromptsubmit_respects_sounds_off(mocker):
    tick = mocker.patch("claude_voice.hook._play_tick")
    cfg = Config(feedback=FeedbackConfig(sounds=False))
    mocker.patch("claude_voice.hook.load_config", return_value=cfg)
    _run_with_stdin({"hook_event_name": "UserPromptSubmit"}, mocker)
    tick.assert_not_called()


def test_pretooluse_plays_tick_and_still_sends_speak(tmp_path, mocker):
    """B: On PreToolUse, tick AND fall through to TTS (dedup handles repeats)."""
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"Checking the docs."}]}}\n'
    )
    tick = mocker.patch("claude_voice.hook._play_tick")
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": None},
    )
    _run_with_stdin(
        {"hook_event_name": "PreToolUse", "transcript_path": str(jsonl)}, mocker
    )
    tick.assert_called_once_with("Purr")
    assert send.called
    assert send.call_args.args[0]["op"] == "speak"


def test_verbatim_flag_skips_summarization(tmp_path, mocker):
    """When the flag file exists, the hook sends raw text and never summarizes
    — even for a response that would normally cross the threshold."""
    flag_path = tmp_path / "next-verbatim.flag"
    flag_path.touch()
    mocker.patch("claude_voice.hook.VERBATIM_FLAG_PATH", flag_path)

    long_text = "Long response. " * 100  # >500 chars
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "message": {"id": "m1", "role": "assistant",
                    "content": [{"type": "text", "text": long_text}]},
    }) + "\n")

    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": "k"},
    )
    summarize_mock = mocker.patch("claude_voice.hook.summarize")
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )

    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )

    summarize_mock.assert_not_called()
    assert send.called
    assert send.call_args.args[0]["text"].startswith("Long response.")
    assert not flag_path.exists()  # flag consumed


def test_verbatim_flag_absent_still_summarizes_by_default(tmp_path, mocker):
    """Without the flag, mode=summary default still routes through summarize()
    — for a response long enough to clear the min_summarize_chars floor."""
    flag_path = tmp_path / "next-verbatim.flag"  # deliberately doesn't exist
    mocker.patch("claude_voice.hook.VERBATIM_FLAG_PATH", flag_path)

    # Long enough to be over min_summarize_chars (default 200)
    long_response = ("This is a long enough response to clear the "
                     "min_summarize_chars floor so summary mode kicks in "
                     "and Haiku actually runs. " * 3)
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "message": {"id": "m2", "role": "assistant",
                    "content": [{"type": "text", "text": long_response}]},
    }) + "\n")

    mocker.patch("claude_voice.hook.load_config", return_value=Config())  # mode="summary" is new default
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": "k"},
    )
    summarize_mock = mocker.patch(
        "claude_voice.hook.summarize", return_value="summarized"
    )
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )

    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )

    summarize_mock.assert_called_once()
    assert send.call_args.args[0]["text"] == "summarized"


def test_short_response_skips_summarize_even_in_summary_mode(tmp_path, mocker):
    """Below min_summarize_chars, hook must speak verbatim — no Haiku round-trip,
    no paraphrase mismatch, no latency hit."""
    jsonl = tmp_path / "t.jsonl"
    short = "Hold a key, speak, and hear the answer."  # ~40 chars, well below floor
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "message": {"id": "m1", "role": "assistant",
                    "content": [{"type": "text", "text": short}]},
    }) + "\n")

    mocker.patch("claude_voice.hook.load_config", return_value=Config())  # default: summary mode, floor 200
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": "k"},
    )
    summarize_mock = mocker.patch(
        "claude_voice.hook.summarize", return_value="paraphrased version"
    )
    send = mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )

    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )

    summarize_mock.assert_not_called()
    assert send.call_args.args[0]["text"] == short


def test_over_5000_chars_forces_summarize_even_below_floor_conflict(tmp_path, mocker):
    """5000-char hard cap wins over anything else — nothing this long should
    ever be read verbatim regardless of mode or floor."""
    jsonl = tmp_path / "t.jsonl"
    huge = "x " * 3000  # 6000 chars
    jsonl.write_text(json.dumps({
        "type": "assistant",
        "message": {"id": "m1", "role": "assistant",
                    "content": [{"type": "text", "text": huge}]},
    }) + "\n")

    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": "k"},
    )
    summarize_mock = mocker.patch(
        "claude_voice.hook.summarize", return_value="short summary"
    )
    mocker.patch(
        "claude_voice.hook.send_message", return_value={"ok": True}
    )

    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )

    summarize_mock.assert_called_once()


def test_daemon_offline_writes_log(tmp_path, mocker):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"hi"}]}}\n'
    )
    mocker.patch("claude_voice.hook.send_message", return_value=None)
    log_path = tmp_path / "hook.log"
    mocker.patch("claude_voice.hook.HOOK_LOG_PATH", log_path)
    mocker.patch("claude_voice.hook.load_config", return_value=Config())
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": None},
    )
    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )
    assert log_path.exists()
    assert "daemon offline" in log_path.read_text()
