import json
from pathlib import Path
from claude_voice.transcript_reader import (
    read_last_assistant,
    read_new_assistant_since_last_user,
)

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


def _line(entry: dict) -> str:
    return json.dumps(entry) + "\n"


def test_reads_last_assistant_message():
    msg = read_last_assistant(FIXTURES / "sample.jsonl")
    assert msg is not None
    assert msg.id == "msg_02"
    assert "I'm well." in msg.content
    assert "How are you?" in msg.content


def test_missing_file_returns_none():
    assert read_last_assistant(Path("/nonexistent.jsonl")) is None


def test_empty_file_returns_none(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert read_last_assistant(p) is None


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "malformed.jsonl"
    p.write_text(
        'not valid json\n'
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"ok"}]}}\n'
        'garbage\n'
    )
    msg = read_last_assistant(p)
    assert msg is not None
    assert msg.content == "ok"


def test_no_assistant_messages_returns_none(tmp_path):
    p = tmp_path / "user_only.jsonl"
    p.write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n')
    assert read_last_assistant(p) is None


def test_string_content_supported(tmp_path):
    p = tmp_path / "str_content.jsonl"
    p.write_text(
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":"plain string"}}\n'
    )
    msg = read_last_assistant(p)
    assert msg is not None
    assert msg.content == "plain string"


# --- read_new_assistant_since_last_user ---

def test_returns_new_assistant_text_after_user_prompt(tmp_path):
    """The assistant emitted text after the user prompt; return it."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        _line({"type": "user", "message": {"role": "user", "content": "hi"}}) +
        _line({"type": "assistant", "message": {"id": "m1", "role": "assistant",
               "content": [{"type": "text", "text": "hello there"}]}})
    )
    msg = read_new_assistant_since_last_user(p)
    assert msg is not None
    assert msg.content == "hello there"


def test_returns_none_when_last_entry_is_user_prompt(tmp_path):
    """User just prompted; assistant hasn't said anything new. The old text
    from the prior turn must NOT be spoken."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        _line({"type": "user", "message": {"role": "user", "content": "first"}}) +
        _line({"type": "assistant", "message": {"id": "m1", "role": "assistant",
               "content": [{"type": "text", "text": "old response"}]}}) +
        _line({"type": "user", "message": {"role": "user", "content": "second"}})
    )
    assert read_new_assistant_since_last_user(p) is None


def test_returns_none_when_only_thinking_and_tool_use_after_user(tmp_path):
    """Assistant emitted thinking + tool_use blocks but no text yet."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        _line({"type": "user", "message": {"role": "user", "content": "do a thing"}}) +
        _line({"type": "assistant", "message": {"id": "m1", "role": "assistant",
               "content": [{"type": "thinking", "thinking": "..."}]}}) +
        _line({"type": "assistant", "message": {"id": "m2", "role": "assistant",
               "content": [{"type": "tool_use", "id": "tu1", "name": "Read"}]}})
    )
    assert read_new_assistant_since_last_user(p) is None


def test_tool_result_entries_are_not_treated_as_user_prompts(tmp_path):
    """Tool results are type=='user' too. They must not act as a turn boundary
    — otherwise we'd never speak interim narration between tool calls."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        _line({"type": "user", "message": {"role": "user", "content": "run some tools"}}) +
        _line({"type": "assistant", "message": {"id": "m1", "role": "assistant",
               "content": [{"type": "text", "text": "let me start"}]}}) +
        _line({"type": "assistant", "message": {"id": "m2", "role": "assistant",
               "content": [{"type": "tool_use", "id": "tu1", "name": "Bash"}]}}) +
        _line({"type": "user", "message": {"role": "user", "content":
               [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]}}) +
        _line({"type": "assistant", "message": {"id": "m3", "role": "assistant",
               "content": [{"type": "text", "text": "now the next step"}]}}) +
        _line({"type": "assistant", "message": {"id": "m4", "role": "assistant",
               "content": [{"type": "tool_use", "id": "tu2", "name": "Bash"}]}})
    )
    msg = read_new_assistant_since_last_user(p)
    assert msg is not None
    assert msg.content == "now the next step"
    assert msg.id == "m3"
