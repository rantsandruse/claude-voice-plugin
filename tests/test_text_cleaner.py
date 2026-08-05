from claude_voice.text_cleaner import clean_for_tts
from pathlib import Path


def test_plain_prose_unchanged():
    assert clean_for_tts("Hello there.") == "Hello there."


def test_strips_fenced_code_block():
    text = "Here is the fix:\n\n```python\ndef foo():\n    pass\n```\n\nDone."
    result = clean_for_tts(text)
    assert "def foo" not in result
    assert "Here is the fix" in result
    assert "Done" in result


def test_strips_inline_code():
    text = "Call `useEffect` after mount."
    result = clean_for_tts(text)
    assert "`" not in result
    assert "useEffect" in result


def test_strips_markdown_headings_and_emphasis():
    text = "# Big Title\n\nThis is **bold** and *italic* text."
    result = clean_for_tts(text)
    assert "#" not in result
    assert "**" not in result
    assert "*" not in result
    assert "Big Title" in result
    assert "bold" in result


def test_strips_list_bullets():
    text = "- first item\n- second item\n"
    result = clean_for_tts(text)
    assert "-" not in result
    assert "first item" in result
    assert "second item" in result


def test_replaces_file_paths():
    text = "I updated src/foo/bar.py with the fix."
    result = clean_for_tts(text)
    assert "src/foo/bar.py" not in result
    assert "a file" in result


def test_collapses_whitespace():
    text = "Line one.\n\n\n\nLine two."
    result = clean_for_tts(text)
    assert "\n\n\n" not in result


def test_only_code_returns_empty():
    text = "```python\nprint('hi')\n```"
    assert clean_for_tts(text) == ""


def test_empty_input_returns_empty():
    assert clean_for_tts("") == ""


def test_tool_use_block_stripped():
    text = "Reading file <tool_use>Read src/main.py</tool_use> now."
    result = clean_for_tts(text)
    assert "tool_use" not in result
    assert "Read src" not in result
    assert "Reading file" in result


def test_realistic_claude_response():
    fixture = Path(__file__).parent / "fixtures" / "responses" / "mixed.md"
    text = fixture.read_text()
    result = clean_for_tts(text)
    assert "def login" not in result
    assert "src/auth/handler.py" not in result
    assert "auth handler" in result
    assert "JWT token" in result
