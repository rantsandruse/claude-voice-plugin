from pathlib import Path
from claude_voice.transcript_reader import read_last_assistant

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


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
