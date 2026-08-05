import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from claude_voice.hook import main
from claude_voice.config import Config


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
