# Voice Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS voice plugin for Claude Code with push-to-talk STT (input) via a menu-bar daemon and TTS (output) via a `Stop` hook.

**Architecture:** Two independent Python processes. (1) A `rumps` menu-bar daemon that handles the global PTT hotkey, records audio, transcribes it, and pastes the transcript into the focused terminal. (2) A `Stop` hook that Claude Code invokes when a response completes; the hook cleans the response text and sends it over a Unix socket to the daemon for TTS playback. The daemon owns TTS playback so the next PTT press can interrupt it.

**Tech Stack:** Python 3.11+, `rumps` (menu bar), `pynput` (global hotkey), `sounddevice` (audio capture), `faster-whisper` (local STT), `httpx` (Deepgram / ElevenLabs), `pyyaml` (config), `click` (CLI), `anthropic` (optional summarization), `pytest` + `pytest-mock` + `respx` (testing).

## Global Constraints

- **Platform:** macOS only. All commands (`pbcopy`, `pbpaste`, `osascript`, `afplay`, `say`) are macOS-native.
- **Python:** 3.11+
- **Package layout:** `src/`-layout, installed via `pip install -e .`
- **Config location:** `~/.config/claude-voice/config.yaml` (never in the repo)
- **Secrets:** Env vars only (`DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`). Loaded from `~/.config/claude-voice/.env`. Never in `config.yaml`.
- **IPC:** Unix domain socket at `~/.config/claude-voice/daemon.sock`. Line-delimited JSON, one message per line.
- **Hook contract:** Claude Code's `Stop` hook invokes `claude-voice-hook` with JSON on stdin containing `hook_event_name`, `session_id`, `transcript_path`, `stop_hook_active`.
- **PTT behavior:** Only the configured PTT key interrupts TTS. Other keypresses do not.
- **Failure mode:** If the daemon isn't running, the Stop hook exits 0 silently (log to `hook.log`). Claude Code proceeds normally — never blocks or fails.
- **TTS content default:** `prose` mode. Force `summary` mode when response exceeds `tts.summary_threshold` characters (default 500). Above 5000 chars is always summarized.
- **Recording minimum:** 300 ms — shorter presses are discarded silently.

---

## File Structure

```
voice_plugin/
├── pyproject.toml
├── README.md
├── install.sh
├── .gitignore
├── docs/superpowers/
│   ├── specs/2026-07-30-voice-plugin-design.md   # already exists
│   └── plans/2026-07-30-voice-plugin.md          # this file
├── config.yaml.example
├── env.example
├── src/claude_voice/
│   ├── __init__.py
│   ├── config.py            # YAML loader, schema, defaults, env overrides
│   ├── text_cleaner.py      # strip code/markdown/paths/tool-use blocks
│   ├── transcript_reader.py # last assistant msg from JSONL
│   ├── ipc.py               # Unix socket server + client, JSON-line protocol
│   ├── recorder.py          # sounddevice capture, WAV output
│   ├── inject.py            # clipboard + ⌘V with restore
│   ├── hotkey.py            # pynput hotkey listener wrapper
│   ├── playback.py          # TTS playback controller, interrupt/replay
│   ├── daemon.py            # rumps App, wires everything
│   ├── cli.py               # `claude-voice` entry point
│   ├── hook.py              # `claude-voice-hook` entry point
│   ├── stt/
│   │   ├── __init__.py
│   │   ├── base.py          # STTProvider protocol
│   │   ├── whisper_local.py # faster-whisper wrapper
│   │   └── deepgram.py      # Deepgram REST call
│   └── tts/
│       ├── __init__.py
│       ├── base.py          # TTSProvider protocol
│       ├── say.py           # macOS say wrapper
│       └── elevenlabs.py    # ElevenLabs stream → afplay
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── responses/       # sample Claude Code assistant messages
    │   └── transcripts/     # sample JSONL transcripts
    ├── test_config.py
    ├── test_text_cleaner.py
    ├── test_transcript_reader.py
    ├── test_ipc.py
    ├── test_inject.py
    ├── test_recorder.py
    ├── test_hotkey.py
    ├── test_playback.py
    ├── test_stt_whisper_local.py
    ├── test_stt_deepgram.py
    ├── test_tts_say.py
    ├── test_tts_elevenlabs.py
    ├── test_hook.py
    └── test_cli.py
```

**Task ordering** starts with pure/leaf modules (no dependencies), builds up to integration:

1. Scaffolding
2. Config
3. Text cleaner
4. Transcript reader
5. IPC
6. STT base + whisper_local
7. STT deepgram
8. TTS base + say
9. TTS elevenlabs
10. Audio recorder
11. Text injector
12. Hotkey listener
13. TTS playback controller
14. Daemon
15. CLI
16. Stop hook
17. Install script

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/claude_voice/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: an installable package `claude_voice` with entry points `claude-voice` and `claude-voice-hook` (they will fail on import until later tasks fill in `cli.main` and `hook.main` — that's fine for now, we only verify `pip install -e .` succeeds).

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
venv/
.env
build/
dist/
*.log
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "claude-voice"
version = "0.1.0"
description = "Voice plugin for Claude Code — push-to-talk STT + Stop-hook TTS"
requires-python = ">=3.11"
dependencies = [
  "rumps>=0.4.0",
  "pynput>=1.7.6",
  "sounddevice>=0.4.6",
  "numpy>=1.26",
  "faster-whisper>=1.0.0",
  "httpx>=0.27",
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
  "click>=8.1",
  "anthropic>=0.30",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "respx>=0.21",
]

[project.scripts]
claude-voice = "claude_voice.cli:main"
claude-voice-hook = "claude_voice.hook:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Create `README.md`**

```markdown
# Claude Voice

A macOS voice plugin for Claude Code. Push-to-talk speech-to-text input; spoken text-to-speech output when Claude finishes a response.

## Install

```bash
git clone <this repo>
cd voice_plugin
./install.sh
```

See `docs/superpowers/specs/2026-07-30-voice-plugin-design.md` for design.
```

- [ ] **Step 4: Create empty package/test files**

- `src/claude_voice/__init__.py` — empty
- `tests/__init__.py` — empty
- `tests/conftest.py` — empty for now

- [ ] **Step 5: Verify install works**

Run:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: install succeeds. `pip show claude-voice` prints package info.

- [ ] **Step 6: Verify pytest runs**

Run: `pytest`
Expected: exits 0 with "no tests ran" (empty test suite is fine).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore README.md src/ tests/
git commit -m "chore: scaffold python package with pyproject.toml"
```

---

## Task 2: Config module

**Files:**
- Create: `src/claude_voice/config.py`
- Create: `tests/test_config.py`
- Create: `config.yaml.example`
- Create: `env.example`

**Interfaces:**
- Produces:
  - `Config` dataclass (frozen) with attributes matching the schema in the spec: `hotkey`, `stt`, `tts`, `feedback`, `logging`.
  - `load_config(path: Path | None = None) -> Config` — loads YAML from `~/.config/claude-voice/config.yaml` by default (override via `path` for tests). Missing file → all defaults. Missing keys → filled with defaults.
  - `secrets() -> dict[str, str | None]` — reads env vars `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`. Returns dict with those keys.
  - `CONFIG_DIR = Path.home() / ".config" / "claude-voice"` module-level constant.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path
import textwrap
import pytest
from claude_voice.config import load_config, secrets, Config


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.hotkey.ptt == "alt_r"
    assert cfg.stt.provider == "whisper_local"
    assert cfg.stt.whisper_local.model == "small"
    assert cfg.tts.enabled is True
    assert cfg.tts.provider == "elevenlabs"
    assert cfg.tts.mode == "prose"
    assert cfg.tts.summary_threshold == 500
    assert cfg.feedback.sounds is True
    assert cfg.feedback.menu_bar is True


def test_load_config_partial_overrides_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        stt:
          provider: deepgram
        tts:
          mode: summary
    """))
    cfg = load_config(p)
    assert cfg.stt.provider == "deepgram"
    assert cfg.tts.mode == "summary"
    # unchanged defaults
    assert cfg.hotkey.ptt == "alt_r"
    assert cfg.tts.provider == "elevenlabs"


def test_secrets_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = secrets()
    assert s["DEEPGRAM_API_KEY"] == "dg-key"
    assert s["ELEVENLABS_API_KEY"] == "el-key"
    assert s["ANTHROPIC_API_KEY"] is None


def test_config_is_frozen():
    cfg = load_config(Path("/nonexistent"))
    with pytest.raises((AttributeError, Exception)):
        cfg.hotkey.ptt = "cmd"  # should be immutable
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `claude_voice.config` module doesn't exist.

- [ ] **Step 3: Implement `config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import yaml

CONFIG_DIR = Path.home() / ".config" / "claude-voice"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"


@dataclass(frozen=True)
class HotkeyConfig:
    ptt: str = "alt_r"
    replay: str = "cmd+shift+r"


@dataclass(frozen=True)
class WhisperLocalConfig:
    model: str = "small"
    device: str = "auto"
    language: str = "en"


@dataclass(frozen=True)
class DeepgramConfig:
    model: str = "nova-2"


@dataclass(frozen=True)
class STTConfig:
    provider: str = "whisper_local"
    whisper_local: WhisperLocalConfig = field(default_factory=WhisperLocalConfig)
    deepgram: DeepgramConfig = field(default_factory=DeepgramConfig)


@dataclass(frozen=True)
class ElevenLabsConfig:
    voice_id: str = "rachel"
    model: str = "eleven_turbo_v2_5"


@dataclass(frozen=True)
class SayConfig:
    voice: str = "Samantha"


@dataclass(frozen=True)
class TTSConfig:
    enabled: bool = True
    provider: str = "elevenlabs"
    mode: str = "prose"
    summary_threshold: int = 500
    elevenlabs: ElevenLabsConfig = field(default_factory=ElevenLabsConfig)
    say: SayConfig = field(default_factory=SayConfig)


@dataclass(frozen=True)
class FeedbackConfig:
    sounds: bool = True
    menu_bar: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "info"
    path: str = "~/.config/claude-voice/daemon.log"


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _merge_dataclass(instance, overrides: dict):
    """Recursively override a frozen dataclass from a dict."""
    if not overrides:
        return instance
    new_values = {}
    for f in instance.__dataclass_fields__.values():
        if f.name in overrides:
            current = getattr(instance, f.name)
            override = overrides[f.name]
            if hasattr(current, "__dataclass_fields__") and isinstance(override, dict):
                new_values[f.name] = _merge_dataclass(current, override)
            else:
                new_values[f.name] = override
    return replace(instance, **new_values) if new_values else instance


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    defaults = Config()
    if not path.exists():
        return defaults
    with open(path) as fp:
        raw = yaml.safe_load(fp) or {}
    return _merge_dataclass(defaults, raw)


def secrets() -> dict[str, str | None]:
    return {
        "DEEPGRAM_API_KEY": os.environ.get("DEEPGRAM_API_KEY"),
        "ELEVENLABS_API_KEY": os.environ.get("ELEVENLABS_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
    }
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Create `config.yaml.example`**

Copy the full schema from the spec (Configuration section) verbatim.

- [ ] **Step 6: Create `env.example`**

```
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
ANTHROPIC_API_KEY=
```

- [ ] **Step 7: Commit**

```bash
git add src/claude_voice/config.py tests/test_config.py config.yaml.example env.example
git commit -m "feat(config): yaml loader with defaults and env-var secrets"
```

---

## Task 3: Text cleaner

**Files:**
- Create: `src/claude_voice/text_cleaner.py`
- Create: `tests/test_text_cleaner.py`
- Create: `tests/fixtures/responses/` (sample assistant messages)

**Interfaces:**
- Produces:
  - `clean_for_tts(text: str) -> str` — takes a raw assistant message string (possibly with markdown, fenced code blocks, inline code, file paths, tool-use blocks), returns the natural-language portion suitable for speaking. Returns `""` when nothing speakable remains.
  - `WHISPER_HALLUCINATION_PATTERNS: list[str]` — module-level list of known Whisper hallucination phrases (case-insensitive substring match) used by STT post-processing later.

- [ ] **Step 1: Write failing tests**

`tests/test_text_cleaner.py`:
```python
from claude_voice.text_cleaner import clean_for_tts


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
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_text_cleaner.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `text_cleaner.py`**

```python
from __future__ import annotations
import re

# Whisper is known to hallucinate these phrases on silence/noise.
WHISPER_HALLUCINATION_PATTERNS: list[str] = [
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "see you next time",
    "bye bye",
    ".",  # single period from empty audio
]

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_TOOL_USE = re.compile(r"<tool_use>.*?</tool_use>", re.DOTALL | re.IGNORECASE)
_FILE_PATH = re.compile(r"(?:[\w\-.]+/)+[\w\-.]+\.[a-zA-Z0-9]{1,6}")
_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_BOLD_ITALIC = re.compile(r"(\*\*|__|\*|_)")
_LIST_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MULTI_NEWLINE = re.compile(r"\n{2,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_for_tts(text: str) -> str:
    if not text:
        return ""
    text = _TOOL_USE.sub("", text)
    text = _FENCED_CODE.sub("", text)
    text = _INLINE_CODE.sub(lambda m: m.group(0).strip("`"), text)
    text = _FILE_PATH.sub("a file", text)
    text = _HEADING.sub("", text)
    text = _BOLD_ITALIC.sub("", text)
    text = _LIST_BULLET.sub("", text)
    text = _NUMBERED_LIST.sub("", text)
    text = _MULTI_NEWLINE.sub("\n", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_text_cleaner.py -v`
Expected: 10 passed. If any fail, adjust regexes.

- [ ] **Step 5: Add real-world fixture test**

Save a sample real Claude Code response to `tests/fixtures/responses/mixed.md`:
```
I'll update the auth handler.

```python
def login(user):
    return jwt.encode({"sub": user.id})
```

Wrote 8 lines to src/auth/handler.py. The endpoint now returns a JWT token instead of a session cookie.
```

Add test:
```python
from pathlib import Path

def test_realistic_claude_response():
    fixture = Path(__file__).parent / "fixtures" / "responses" / "mixed.md"
    text = fixture.read_text()
    result = clean_for_tts(text)
    assert "def login" not in result
    assert "src/auth/handler.py" not in result
    assert "auth handler" in result
    assert "JWT token" in result
```

Run: `pytest tests/test_text_cleaner.py::test_realistic_claude_response -v` — expect PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice/text_cleaner.py tests/test_text_cleaner.py tests/fixtures/
git commit -m "feat(text_cleaner): strip code, markdown, paths for TTS"
```

---

## Task 4: Transcript reader

**Files:**
- Create: `src/claude_voice/transcript_reader.py`
- Create: `tests/test_transcript_reader.py`
- Create: `tests/fixtures/transcripts/sample.jsonl`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `read_last_assistant(transcript_path: Path) -> AssistantMessage | None` where `AssistantMessage` is a small frozen dataclass with `id: str` and `content: str`.
  - Returns `None` if file missing, empty, or no assistant message found.
  - Handles JSONL with malformed lines by skipping them (log to `stderr` at debug level).
  - Concatenates multiple `text` content blocks in the message into a single string separated by `\n\n`.

- [ ] **Step 1: Create fixture `tests/fixtures/transcripts/sample.jsonl`**

```
{"type":"user","message":{"role":"user","content":"Hello"},"uuid":"u1"}
{"type":"assistant","message":{"id":"msg_01","role":"assistant","content":[{"type":"text","text":"Hi there!"}]},"uuid":"a1"}
{"type":"user","message":{"role":"user","content":"How are you?"},"uuid":"u2"}
{"type":"assistant","message":{"id":"msg_02","role":"assistant","content":[{"type":"text","text":"I'm well."},{"type":"text","text":"How are you?"}]},"uuid":"a2"}
```

- [ ] **Step 2: Write failing tests**

`tests/test_transcript_reader.py`:
```python
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
```

- [ ] **Step 3: Run tests — expect ImportError**

Run: `pytest tests/test_transcript_reader.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `transcript_reader.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import sys


@dataclass(frozen=True)
class AssistantMessage:
    id: str
    content: str


def read_last_assistant(transcript_path: Path) -> AssistantMessage | None:
    if not transcript_path.exists():
        return None
    last: AssistantMessage | None = None
    with open(transcript_path) as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                print(f"[transcript_reader] skipping malformed line", file=sys.stderr)
                continue
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            msg_id = msg.get("id") or entry.get("uuid") or ""
            content = _extract_content(msg.get("content"))
            if content:
                last = AssistantMessage(id=msg_id, content=content)
    return last


def _extract_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if text:
                    parts.append(text)
        return "\n\n".join(parts)
    return ""
```

- [ ] **Step 5: Run tests — expect all pass**

Run: `pytest tests/test_transcript_reader.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice/transcript_reader.py tests/test_transcript_reader.py tests/fixtures/transcripts/
git commit -m "feat(transcript_reader): read last assistant msg from JSONL"
```

---

## Task 5: IPC (Unix socket)

**Files:**
- Create: `src/claude_voice/ipc.py`
- Create: `tests/test_ipc.py`

**Interfaces:**
- Produces:
  - `SOCKET_PATH: Path = CONFIG_DIR / "daemon.sock"` module constant
  - `send_message(msg: dict, socket_path: Path | None = None, timeout: float = 2.0) -> dict | None` — connects, sends one JSON line, reads one JSON line reply, closes. Returns `None` if daemon not running.
  - `class IPCServer` — thread-based server:
    - `IPCServer(socket_path: Path, handlers: dict[str, Callable[[dict], dict]])`
    - `.start()` / `.stop()`
    - Each accepted connection: read one JSON line, dispatch to `handlers[msg["op"]]`, write reply as one JSON line, close.
    - Unknown `op` → reply `{"ok": false, "error": "unknown op"}`.
    - Malformed JSON → reply `{"ok": false, "error": "malformed"}`.

- [ ] **Step 1: Write failing tests**

`tests/test_ipc.py`:
```python
import time
from pathlib import Path
import pytest
from claude_voice.ipc import IPCServer, send_message


@pytest.fixture
def socket_path(tmp_path):
    return tmp_path / "test.sock"


def test_send_message_no_daemon_returns_none(socket_path):
    assert send_message({"op": "ping"}, socket_path=socket_path, timeout=0.5) is None


def test_server_dispatches_to_handler(socket_path):
    calls = []

    def handler(msg):
        calls.append(msg)
        return {"ok": True, "echo": msg.get("text")}

    server = IPCServer(socket_path, {"ping": handler})
    server.start()
    try:
        reply = send_message({"op": "ping", "text": "hi"}, socket_path=socket_path)
        assert reply == {"ok": True, "echo": "hi"}
        assert calls == [{"op": "ping", "text": "hi"}]
    finally:
        server.stop()


def test_server_unknown_op_returns_error(socket_path):
    server = IPCServer(socket_path, {})
    server.start()
    try:
        reply = send_message({"op": "nope"}, socket_path=socket_path)
        assert reply is not None
        assert reply["ok"] is False
    finally:
        server.stop()


def test_server_handles_malformed_message(socket_path):
    import socket
    server = IPCServer(socket_path, {})
    server.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(socket_path))
        s.sendall(b"not json\n")
        reply = s.recv(1024).decode()
        s.close()
        assert "malformed" in reply
    finally:
        server.stop()


def test_server_removes_stale_socket(socket_path):
    socket_path.touch()  # simulate leftover socket file
    server = IPCServer(socket_path, {})
    server.start()
    try:
        assert socket_path.exists()
    finally:
        server.stop()
    # after stop, socket should be cleaned up
    assert not socket_path.exists()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_ipc.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `ipc.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Callable
import json
import os
import socket
import threading

from .config import CONFIG_DIR

SOCKET_PATH = CONFIG_DIR / "daemon.sock"


def send_message(
    msg: dict,
    socket_path: Path | None = None,
    timeout: float = 2.0,
) -> dict | None:
    path = socket_path or SOCKET_PATH
    if not path.exists():
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
        return None
    try:
        s.sendall((json.dumps(msg) + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break
        line = data.decode().splitlines()[0] if data else ""
        return json.loads(line) if line else None
    except (socket.timeout, json.JSONDecodeError, OSError):
        return None
    finally:
        s.close()


class IPCServer:
    def __init__(self, socket_path: Path, handlers: dict[str, Callable[[dict], dict]]):
        self._path = socket_path
        self._handlers = handlers
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._path.exists():
            self._path.unlink()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(0.5)
        self._sock.bind(str(self._path))
        self._sock.listen(8)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._path.exists():
            self._path.unlink()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()  # type: ignore
            except (socket.timeout, OSError):
                continue
            threading.Thread(
                target=self._handle_conn, args=(conn,), daemon=True
            ).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2.0)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            line = data.decode().split("\n", 1)[0]
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                conn.sendall(b'{"ok":false,"error":"malformed"}\n')
                return
            op = msg.get("op")
            handler = self._handlers.get(op)
            if not handler:
                conn.sendall(b'{"ok":false,"error":"unknown op"}\n')
                return
            try:
                reply = handler(msg) or {"ok": True}
            except Exception as e:
                reply = {"ok": False, "error": str(e)}
            conn.sendall((json.dumps(reply) + "\n").encode())
        finally:
            conn.close()
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_ipc.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/ipc.py tests/test_ipc.py
git commit -m "feat(ipc): unix socket server + client for daemon comms"
```

---

## Task 6: STT base + faster-whisper local

**Files:**
- Create: `src/claude_voice/stt/__init__.py` (empty)
- Create: `src/claude_voice/stt/base.py`
- Create: `src/claude_voice/stt/whisper_local.py`
- Create: `tests/test_stt_whisper_local.py`

**Interfaces:**
- Consumes: `WhisperLocalConfig` from `config.py`; `WHISPER_HALLUCINATION_PATTERNS` from `text_cleaner.py`.
- Produces:
  - `class STTProvider(Protocol)`:
    - `transcribe(wav_path: Path) -> str` — returns cleaned transcript or `""` for silence/hallucination.
  - `class WhisperLocalProvider`:
    - `__init__(self, config: WhisperLocalConfig)`
    - `transcribe(wav_path: Path) -> str`
    - Lazy-loads the `faster_whisper.WhisperModel` on first call, keeps resident.
    - Post-processing: normalize whitespace, strip trailing period, drop the transcript if it matches any `WHISPER_HALLUCINATION_PATTERNS` (case-insensitive substring match on the stripped transcript).

- [ ] **Step 1: Write failing tests**

`tests/test_stt_whisper_local.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from claude_voice.config import WhisperLocalConfig
from claude_voice.stt.whisper_local import WhisperLocalProvider


class FakeSegment:
    def __init__(self, text): self.text = text


def _mock_model(segments_text: list[str]):
    model = MagicMock()
    model.transcribe.return_value = ([FakeSegment(t) for t in segments_text], None)
    return model


def test_transcribe_concats_segments(mocker):
    fake = _mock_model([" Hello ", " there. "])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    result = p.transcribe(Path("/tmp/fake.wav"))
    assert result == "Hello there"  # normalized, trailing period stripped


def test_transcribe_filters_hallucination(mocker):
    fake = _mock_model(["Thanks for watching!"])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    assert p.transcribe(Path("/tmp/fake.wav")) == ""


def test_transcribe_empty_returns_empty(mocker):
    fake = _mock_model([])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    assert p.transcribe(Path("/tmp/fake.wav")) == ""


def test_model_loaded_once(mocker):
    fake = _mock_model(["hi"])
    ctor = mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    p.transcribe(Path("/tmp/f.wav"))
    p.transcribe(Path("/tmp/f.wav"))
    assert ctor.call_count == 1
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_stt_whisper_local.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `stt/base.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Protocol


class STTProvider(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...
```

- [ ] **Step 4: Implement `stt/whisper_local.py`**

```python
from __future__ import annotations
from pathlib import Path
import re

from faster_whisper import WhisperModel

from ..config import WhisperLocalConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS


class WhisperLocalProvider:
    def __init__(self, config: WhisperLocalConfig):
        self._config = config
        self._model: WhisperModel | None = None

    def _model_get(self) -> WhisperModel:
        if self._model is None:
            device = "auto" if self._config.device == "auto" else self._config.device
            compute_type = "int8" if device != "cuda" else "float16"
            self._model = WhisperModel(
                self._config.model, device=device, compute_type=compute_type
            )
        return self._model

    def transcribe(self, wav_path: Path) -> str:
        segments, _ = self._model_get().transcribe(
            str(wav_path), language=self._config.language
        )
        raw = " ".join(seg.text.strip() for seg in segments).strip()
        return self._post_process(raw)

    @staticmethod
    def _post_process(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = text.rstrip(".")
        if not text:
            return ""
        low = text.lower()
        for phrase in WHISPER_HALLUCINATION_PATTERNS:
            if phrase in low and len(text) < len(phrase) + 5:
                return ""
        return text
```

- [ ] **Step 5: Run tests — expect all pass**

Run: `pytest tests/test_stt_whisper_local.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice/stt/ tests/test_stt_whisper_local.py
git commit -m "feat(stt): faster-whisper local provider with hallucination filter"
```

---

## Task 7: STT Deepgram

**Files:**
- Create: `src/claude_voice/stt/deepgram.py`
- Create: `tests/test_stt_deepgram.py`

**Interfaces:**
- Consumes: `DeepgramConfig` from `config.py`; `DEEPGRAM_API_KEY` env var.
- Produces:
  - `class DeepgramProvider`:
    - `__init__(self, config: DeepgramConfig, api_key: str)`
    - `transcribe(wav_path: Path) -> str`
    - POSTs the WAV bytes to `https://api.deepgram.com/v1/listen?model=<model>&smart_format=true` with `Authorization: Token <key>` and `Content-Type: audio/wav`.
    - Extracts `results.channels[0].alternatives[0].transcript` from the JSON response.
    - Same post-processing as whisper_local (normalize whitespace, strip trailing period, filter hallucinations).
    - Raises `RuntimeError` on non-2xx (caller handles fallback).

- [ ] **Step 1: Write failing tests**

`tests/test_stt_deepgram.py`:
```python
from pathlib import Path
import pytest
import respx
import httpx
from claude_voice.config import DeepgramConfig
from claude_voice.stt.deepgram import DeepgramProvider


@pytest.fixture
def wav_file(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF....WAVEfmt " + b"\x00" * 100)
    return p


@respx.mock
def test_transcribe_success(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={
            "results": {
                "channels": [{"alternatives": [{"transcript": "hello world."}]}]
            }
        })
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == "hello world"


@respx.mock
def test_transcribe_filters_hallucination(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={
            "results": {
                "channels": [{"alternatives": [{"transcript": "Thanks for watching"}]}]
            }
        })
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == ""


@respx.mock
def test_transcribe_raises_on_non_2xx(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(401, json={"err": "bad key"})
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    with pytest.raises(RuntimeError):
        p.transcribe(wav_file)


@respx.mock
def test_transcribe_empty_result(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={"results": {"channels": []}})
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == ""
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_stt_deepgram.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `stt/deepgram.py`**

```python
from __future__ import annotations
from pathlib import Path
import re
import httpx

from ..config import DeepgramConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS

_URL = "https://api.deepgram.com/v1/listen"


class DeepgramProvider:
    def __init__(self, config: DeepgramConfig, api_key: str):
        self._config = config
        self._api_key = api_key

    def transcribe(self, wav_path: Path) -> str:
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }
        params = {"model": self._config.model, "smart_format": "true"}
        with open(wav_path, "rb") as fp:
            data = fp.read()
        r = httpx.post(_URL, headers=headers, params=params, content=data, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Deepgram {r.status_code}: {r.text[:200]}")
        payload = r.json()
        try:
            transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError):
            return ""
        return self._post_process(transcript)

    @staticmethod
    def _post_process(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip().rstrip(".")
        if not text:
            return ""
        low = text.lower()
        for phrase in WHISPER_HALLUCINATION_PATTERNS:
            if phrase in low and len(text) < len(phrase) + 5:
                return ""
        return text
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_stt_deepgram.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/stt/deepgram.py tests/test_stt_deepgram.py
git commit -m "feat(stt): deepgram REST provider"
```

---

## Task 8: TTS base + macOS `say`

**Files:**
- Create: `src/claude_voice/tts/__init__.py` (empty)
- Create: `src/claude_voice/tts/base.py`
- Create: `src/claude_voice/tts/say.py`
- Create: `tests/test_tts_say.py`

**Interfaces:**
- Consumes: `SayConfig` from `config.py`.
- Produces:
  - `class TTSProvider(Protocol)`:
    - `speak(text: str) -> subprocess.Popen` — starts synthesis in a subprocess, returns the `Popen` handle so the caller can `.terminate()` for interrupt. Non-blocking.
  - `class SayProvider`:
    - `__init__(self, config: SayConfig)`
    - `speak(text: str) -> subprocess.Popen`
    - Runs `subprocess.Popen(["say", "-v", self._config.voice, text])`.
    - Empty text → raises `ValueError` (caller shouldn't call with empty).

- [ ] **Step 1: Write failing tests**

`tests/test_tts_say.py`:
```python
import subprocess
import pytest
from claude_voice.config import SayConfig
from claude_voice.tts.say import SayProvider


def test_speak_starts_subprocess(mocker):
    popen_mock = mocker.patch(
        "claude_voice.tts.say.subprocess.Popen",
        return_value=mocker.MagicMock(spec=subprocess.Popen),
    )
    p = SayProvider(SayConfig(voice="Samantha"))
    handle = p.speak("hello")
    popen_mock.assert_called_once()
    args = popen_mock.call_args[0][0]
    assert args == ["say", "-v", "Samantha", "hello"]
    assert handle is popen_mock.return_value


def test_speak_empty_raises():
    p = SayProvider(SayConfig())
    with pytest.raises(ValueError):
        p.speak("")

    with pytest.raises(ValueError):
        p.speak("   ")
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_tts_say.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `tts/base.py`**

```python
from __future__ import annotations
import subprocess
from typing import Protocol


class TTSProvider(Protocol):
    def speak(self, text: str) -> subprocess.Popen: ...
```

- [ ] **Step 4: Implement `tts/say.py`**

```python
from __future__ import annotations
import subprocess

from ..config import SayConfig


class SayProvider:
    def __init__(self, config: SayConfig):
        self._config = config

    def speak(self, text: str) -> subprocess.Popen:
        if not text or not text.strip():
            raise ValueError("empty text")
        return subprocess.Popen(["say", "-v", self._config.voice, text])
```

- [ ] **Step 5: Run tests — expect all pass**

Run: `pytest tests/test_tts_say.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/claude_voice/tts/ tests/test_tts_say.py
git commit -m "feat(tts): macOS say provider"
```

---

## Task 9: TTS ElevenLabs

**Files:**
- Create: `src/claude_voice/tts/elevenlabs.py`
- Create: `tests/test_tts_elevenlabs.py`

**Interfaces:**
- Consumes: `ElevenLabsConfig`; `ELEVENLABS_API_KEY` env var.
- Produces:
  - `class ElevenLabsProvider`:
    - `__init__(self, config: ElevenLabsConfig, api_key: str)`
    - `speak(text: str) -> subprocess.Popen` — starts `afplay -` subprocess with `stdin=PIPE`, spawns a background thread that streams the ElevenLabs MP3 response and pipes bytes into `afplay.stdin`. Returns the `afplay` Popen handle; caller can `.terminate()` to stop playback (thread will detect broken pipe and exit).
    - URL: `https://api.elevenlabs.io/v1/text-to-speech/<voice_id>/stream`
    - Headers: `xi-api-key: <key>`, `Content-Type: application/json`, `Accept: audio/mpeg`
    - Body: `{"text": text, "model_id": self._config.model}`
    - Non-2xx: log and raise `RuntimeError` (caller falls back to `say`).

- [ ] **Step 1: Write failing tests**

`tests/test_tts_elevenlabs.py`:
```python
import subprocess
import pytest
import respx
import httpx
from claude_voice.config import ElevenLabsConfig
from claude_voice.tts.elevenlabs import ElevenLabsProvider


@respx.mock
def test_speak_pipes_stream_to_afplay(mocker):
    route = respx.post(
        "https://api.elevenlabs.io/v1/text-to-speech/rachel/stream"
    ).mock(return_value=httpx.Response(200, content=b"MP3AUDIO"))

    popen_mock = mocker.patch(
        "claude_voice.tts.elevenlabs.subprocess.Popen",
        return_value=mocker.MagicMock(spec=subprocess.Popen, stdin=mocker.MagicMock()),
    )

    p = ElevenLabsProvider(ElevenLabsConfig(voice_id="rachel"), api_key="k")
    handle = p.speak("hello")

    # afplay was started
    assert popen_mock.call_args[0][0] == ["afplay", "-"]
    # give the streaming thread a moment
    import time; time.sleep(0.1)
    handle.stdin.write.assert_called()  # bytes were streamed


@respx.mock
def test_speak_raises_on_non_2xx():
    respx.post("https://api.elevenlabs.io/v1/text-to-speech/rachel/stream").mock(
        return_value=httpx.Response(401, content=b"nope")
    )
    p = ElevenLabsProvider(ElevenLabsConfig(voice_id="rachel"), api_key="k")
    with pytest.raises(RuntimeError):
        p.speak("hello")


def test_speak_empty_raises():
    p = ElevenLabsProvider(ElevenLabsConfig(), api_key="k")
    with pytest.raises(ValueError):
        p.speak("")
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_tts_elevenlabs.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `tts/elevenlabs.py`**

```python
from __future__ import annotations
import subprocess
import threading
import httpx

from ..config import ElevenLabsConfig


class ElevenLabsProvider:
    def __init__(self, config: ElevenLabsConfig, api_key: str):
        self._config = config
        self._api_key = api_key

    def speak(self, text: str) -> subprocess.Popen:
        if not text or not text.strip():
            raise ValueError("empty text")
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/"
            f"{self._config.voice_id}/stream"
        )
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = {"text": text, "model_id": self._config.model}

        # Probe with a HEAD-style small request? No — do a streaming GET/POST
        # and raise if the initial response is non-2xx before spawning afplay.
        client = httpx.Client(timeout=60)
        resp = client.stream("POST", url, headers=headers, json=body).__enter__()
        try:
            if resp.status_code >= 300:
                body_snippet = resp.read()[:200].decode(errors="replace")
                raise RuntimeError(f"ElevenLabs {resp.status_code}: {body_snippet}")
        except RuntimeError:
            resp.close()
            client.close()
            raise

        afplay = subprocess.Popen(["afplay", "-"], stdin=subprocess.PIPE)

        def _pump():
            try:
                for chunk in resp.iter_bytes():
                    if afplay.stdin is None or afplay.poll() is not None:
                        break
                    try:
                        afplay.stdin.write(chunk)
                    except (BrokenPipeError, ValueError):
                        break
            finally:
                try:
                    if afplay.stdin:
                        afplay.stdin.close()
                except Exception:
                    pass
                resp.close()
                client.close()

        threading.Thread(target=_pump, daemon=True).start()
        return afplay
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_tts_elevenlabs.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/tts/elevenlabs.py tests/test_tts_elevenlabs.py
git commit -m "feat(tts): elevenlabs streaming provider piped to afplay"
```

---

## Task 10: Audio recorder

**Files:**
- Create: `src/claude_voice/recorder.py`
- Create: `tests/test_recorder.py`

**Interfaces:**
- Consumes: nothing external besides `sounddevice`, `numpy`, stdlib `wave`.
- Produces:
  - `class Recorder`:
    - `__init__(self, sample_rate: int = 16000, output_dir: Path = Path("/tmp/claude-voice"))`
    - `start()` — begin capturing to an in-memory buffer.
    - `stop() -> Path | None` — stop capture. If total captured duration >= 300 ms → writes 16-bit PCM mono WAV to `output_dir/<timestamp>.wav` and returns the path. Otherwise → returns `None` (too short, discarded).
    - Idempotent: `stop()` before `start()` is a no-op returning `None`.

- [ ] **Step 1: Write failing tests**

`tests/test_recorder.py`:
```python
import wave
import numpy as np
import pytest
from claude_voice.recorder import Recorder


class FakeInputStream:
    """Simulates sounddevice.InputStream with an injected callback."""
    def __init__(self, samplerate, channels, dtype, callback, blocksize=0):
        self.callback = callback
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self._active = False

    def start(self): self._active = True
    def stop(self): self._active = False
    def close(self): pass

    def feed(self, seconds: float):
        n = int(self.samplerate * seconds)
        frames = np.zeros((n, self.channels), dtype=self.dtype)
        self.callback(frames, n, None, None)


@pytest.fixture
def fake_stream(mocker):
    holder = {}
    def make(*args, **kwargs):
        stream = FakeInputStream(
            samplerate=kwargs["samplerate"],
            channels=kwargs["channels"],
            dtype=kwargs["dtype"],
            callback=kwargs["callback"],
        )
        holder["stream"] = stream
        return stream
    mocker.patch("claude_voice.recorder.sd.InputStream", side_effect=make)
    return holder


def test_recording_under_300ms_discarded(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.1)  # 100ms
    assert rec.stop() is None


def test_recording_over_300ms_written(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.5)  # 500ms
    path = rec.stop()
    assert path is not None
    assert path.exists()
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2  # 16-bit


def test_stop_before_start_returns_none(tmp_path):
    rec = Recorder(output_dir=tmp_path)
    assert rec.stop() is None
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_recorder.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `recorder.py`**

```python
from __future__ import annotations
from pathlib import Path
import time
import wave
import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        output_dir: Path = Path("/tmp/claude-voice"),
    ):
        self._sample_rate = sample_rate
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._active = False

    def _callback(self, indata, frames, time_info, status):
        if self._active:
            self._buffer.append(indata.copy())

    def start(self) -> None:
        self._buffer = []
        self._active = True
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> Path | None:
        if not self._active or self._stream is None:
            return None
        self._active = False
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._buffer:
            return None
        audio = np.concatenate(self._buffer, axis=0)
        duration = len(audio) / self._sample_rate
        if duration < 0.3:
            return None
        path = self._output_dir / f"{int(time.time() * 1000)}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._sample_rate)
            w.writeframes(audio.tobytes())
        return path
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_recorder.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/recorder.py tests/test_recorder.py
git commit -m "feat(recorder): sounddevice capture with min-duration guard"
```

---

## Task 11: Text injector

**Files:**
- Create: `src/claude_voice/inject.py`
- Create: `tests/test_inject.py`

**Interfaces:**
- Produces:
  - `inject(text: str) -> None` — saves `pbpaste` output, calls `pbcopy` with `text`, runs `osascript -e 'tell application "System Events" to keystroke "v" using command down'`, sleeps 150 ms, restores the original `pbpaste` output via a second `pbcopy`.
  - If `pbpaste` returns bytes that don't decode as UTF-8 (e.g., non-text clipboard), skip the restore and log a warning to stderr.

- [ ] **Step 1: Write failing tests**

`tests/test_inject.py`:
```python
import subprocess
from claude_voice.inject import inject


def test_inject_pastes_and_restores_clipboard(mocker):
    # pbpaste returns "prev clipboard"
    check_output = mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"prev clipboard",
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("new text")

    # Sequence: check_output(pbpaste), run(pbcopy new), run(osascript ⌘V), run(pbcopy prev)
    check_output.assert_called_once_with(["pbpaste"])
    calls = run.call_args_list
    # first run: pbcopy of "new text"
    assert calls[0].args[0] == ["pbcopy"]
    assert calls[0].kwargs["input"] == b"new text"
    # second run: osascript keystroke
    assert calls[1].args[0][0] == "osascript"
    assert "keystroke" in " ".join(calls[1].args[0])
    # third run: pbcopy restore
    assert calls[2].args[0] == ["pbcopy"]
    assert calls[2].kwargs["input"] == b"prev clipboard"


def test_inject_handles_non_utf8_clipboard(mocker):
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        return_value=b"\xff\xfe\x00\x01",  # not UTF-8
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello")

    # pbcopy new + osascript, but NO restore (skipped)
    ops = [c.args[0] for c in run.call_args_list]
    assert ops.count(["pbcopy"]) == 1


def test_inject_handles_pbpaste_failure(mocker):
    mocker.patch(
        "claude_voice.inject.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "pbpaste"),
    )
    run = mocker.patch("claude_voice.inject.subprocess.run")
    mocker.patch("claude_voice.inject.time.sleep")

    inject("hello")

    ops = [c.args[0] for c in run.call_args_list]
    # still does pbcopy + osascript, just no restore
    assert ["pbcopy"] in ops
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_inject.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `inject.py`**

```python
from __future__ import annotations
import subprocess
import sys
import time

_KEYSTROKE = 'tell application "System Events" to keystroke "v" using command down'


def inject(text: str) -> None:
    if not text:
        return
    saved: bytes | None = None
    try:
        saved = subprocess.check_output(["pbpaste"])
        saved.decode("utf-8")  # verify it's text; raises otherwise
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        saved = None
        print("[inject] non-text clipboard; skipping restore", file=sys.stderr)

    subprocess.run(["pbcopy"], input=text.encode())
    subprocess.run(["osascript", "-e", _KEYSTROKE])
    time.sleep(0.15)
    if saved is not None:
        subprocess.run(["pbcopy"], input=saved)
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_inject.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/inject.py tests/test_inject.py
git commit -m "feat(inject): clipboard paste with restore"
```

---

## Task 12: Hotkey listener

**Files:**
- Create: `src/claude_voice/hotkey.py`
- Create: `tests/test_hotkey.py`

**Interfaces:**
- Consumes: `HotkeyConfig`.
- Produces:
  - `class HotkeyEvent(Enum)`: `PTT_DOWN`, `PTT_UP`.
  - `class HotkeyListener`:
    - `__init__(self, config: HotkeyConfig, on_event: Callable[[HotkeyEvent], None])`
    - `.start()` / `.stop()` — spawns / stops a `pynput.keyboard.Listener` in a background thread.
    - When the configured PTT key is pressed → calls `on_event(HotkeyEvent.PTT_DOWN)`.
    - When released → calls `on_event(HotkeyEvent.PTT_UP)`.
    - Auto-repeat safety: consecutive `PTT_DOWN` without an intervening `PTT_UP` are ignored.
  - Key parsing: `_parse_key(name: str) -> pynput.keyboard.Key | pynput.keyboard.KeyCode`. Supports `alt_r`, `alt_l`, `cmd_r`, `cmd_l`, `ctrl_r`, `ctrl_l`, `shift_r`, `shift_l`, `f1..f12`. Unknown → raises `ValueError`.

- [ ] **Step 1: Write failing tests**

`tests/test_hotkey.py`:
```python
import pytest
from unittest.mock import MagicMock
from pynput import keyboard
from claude_voice.config import HotkeyConfig
from claude_voice.hotkey import HotkeyListener, HotkeyEvent, _parse_key


def test_parse_key_alt_r():
    assert _parse_key("alt_r") == keyboard.Key.alt_r


def test_parse_key_f1():
    assert _parse_key("f1") == keyboard.Key.f1


def test_parse_key_unknown_raises():
    with pytest.raises(ValueError):
        _parse_key("wat")


def test_ptt_down_up_events(mocker):
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    # simulate pynput callbacks
    listener._on_press(keyboard.Key.alt_r)
    listener._on_release(keyboard.Key.alt_r)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]


def test_ignores_non_ptt_keys():
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    listener._on_press(keyboard.Key.shift)
    listener._on_release(keyboard.Key.shift)
    assert events == []


def test_auto_repeat_ignored():
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    listener._on_press(keyboard.Key.alt_r)
    listener._on_press(keyboard.Key.alt_r)  # OS auto-repeat
    listener._on_press(keyboard.Key.alt_r)
    listener._on_release(keyboard.Key.alt_r)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_hotkey.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `hotkey.py`**

```python
from __future__ import annotations
from enum import Enum, auto
from typing import Callable
from pynput import keyboard

from .config import HotkeyConfig


class HotkeyEvent(Enum):
    PTT_DOWN = auto()
    PTT_UP = auto()


def _parse_key(name: str):
    name = name.lower()
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        raise ValueError(f"unknown key name: {name}")


class HotkeyListener:
    def __init__(self, config: HotkeyConfig, on_event: Callable[[HotkeyEvent], None]):
        self._ptt = _parse_key(config.ptt)
        self._on_event = on_event
        self._listener: keyboard.Listener | None = None
        self._is_down = False

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        if key != self._ptt:
            return
        if self._is_down:
            return
        self._is_down = True
        self._on_event(HotkeyEvent.PTT_DOWN)

    def _on_release(self, key) -> None:
        if key != self._ptt:
            return
        if not self._is_down:
            return
        self._is_down = False
        self._on_event(HotkeyEvent.PTT_UP)
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_hotkey.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hotkey.py tests/test_hotkey.py
git commit -m "feat(hotkey): pynput PTT listener with auto-repeat guard"
```

---

## Task 13: TTS playback controller

**Files:**
- Create: `src/claude_voice/playback.py`
- Create: `tests/test_playback.py`

**Interfaces:**
- Consumes: `TTSProvider` protocol from `tts/base.py`.
- Produces:
  - `class PlaybackController`:
    - `__init__(self, provider: TTSProvider, fallback: TTSProvider | None = None)`
    - `.speak(text: str, response_id: str) -> bool` — if already playing, interrupts. Calls `provider.speak(text)`; on `RuntimeError` or `httpx` error, falls back to `fallback` if provided. Stores `(response_id, text)` for replay. Returns `True` if playback started, `False` otherwise.
    - `.interrupt() -> None` — terminates the current subprocess if any. Idempotent.
    - `.replay_last() -> bool` — re-speaks the last stored text. Returns `False` if nothing to replay.
    - `.is_playing() -> bool` — subprocess exists and hasn't exited.
    - Thread-safety: single lock around `_current` and `_last`.

- [ ] **Step 1: Write failing tests**

`tests/test_playback.py`:
```python
import subprocess
from unittest.mock import MagicMock
from claude_voice.playback import PlaybackController


def _mock_provider(handle=None):
    provider = MagicMock()
    provider.speak.return_value = handle or MagicMock(spec=subprocess.Popen)
    return provider


def test_speak_calls_provider():
    handle = MagicMock(spec=subprocess.Popen)
    handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    assert p.speak("hello", "id1") is True
    provider.speak.assert_called_once_with("hello")


def test_speak_interrupts_previous():
    h1 = MagicMock(spec=subprocess.Popen); h1.poll.return_value = None
    h2 = MagicMock(spec=subprocess.Popen); h2.poll.return_value = None
    provider = MagicMock()
    provider.speak.side_effect = [h1, h2]
    p = PlaybackController(provider)
    p.speak("first", "id1")
    p.speak("second", "id2")
    h1.terminate.assert_called_once()


def test_interrupt_terminates():
    handle = MagicMock(spec=subprocess.Popen); handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    p.speak("x", "id1")
    p.interrupt()
    handle.terminate.assert_called_once()


def test_interrupt_when_idle_is_noop():
    p = PlaybackController(_mock_provider())
    p.interrupt()  # should not raise


def test_replay_last_speaks_stored_text():
    handle = MagicMock(spec=subprocess.Popen); handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    p.speak("hello", "id1")
    p.interrupt()
    p.replay_last()
    assert provider.speak.call_count == 2
    assert provider.speak.call_args_list[1].args == ("hello",)


def test_replay_when_nothing_stored():
    p = PlaybackController(_mock_provider())
    assert p.replay_last() is False


def test_falls_back_on_provider_error():
    provider = MagicMock()
    provider.speak.side_effect = RuntimeError("network down")
    fallback = MagicMock()
    fallback_handle = MagicMock(spec=subprocess.Popen); fallback_handle.poll.return_value = None
    fallback.speak.return_value = fallback_handle
    p = PlaybackController(provider, fallback=fallback)
    assert p.speak("hi", "id1") is True
    fallback.speak.assert_called_once_with("hi")
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_playback.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `playback.py`**

```python
from __future__ import annotations
import subprocess
import threading
import sys
from .tts.base import TTSProvider


class PlaybackController:
    def __init__(self, provider: TTSProvider, fallback: TTSProvider | None = None):
        self._provider = provider
        self._fallback = fallback
        self._current: subprocess.Popen | None = None
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
            return True

    def interrupt(self) -> None:
        with self._lock:
            if self._current is not None and self._current.poll() is None:
                try:
                    self._current.terminate()
                except Exception:
                    pass
            self._current = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._current is not None and self._current.poll() is None

    def replay_last(self) -> bool:
        with self._lock:
            last = self._last
        if last is None:
            return False
        return self.speak(last[1], last[0])
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_playback.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/playback.py tests/test_playback.py
git commit -m "feat(playback): TTS controller with interrupt, replay, fallback"
```

---

## Task 14: Daemon (rumps menu bar app)

**Files:**
- Create: `src/claude_voice/daemon.py`
- Create: `tests/test_daemon.py`

**Interfaces:**
- Consumes: everything so far.
- Produces:
  - `class DaemonCore` (non-UI, testable):
    - `__init__(self, config, recorder, hotkey_listener, stt, playback, ipc, inject_fn, on_state_change, dispatch=None)` — `dispatch: Callable[[Callable, tuple], None]` runs a callable with args; defaults to spawning a background daemon thread. Tests pass `dispatch=lambda fn, args: fn(*args)` for synchronous execution.
    - `handle_hotkey(event: HotkeyEvent)` — PTT_DOWN: if playing → interrupt; start recorder; play start-tick. PTT_UP: if already busy transcribing → play busy-tick and return; else stop recorder, dispatch `run_transcribe_job(wav)` via `self._dispatch`.
    - `run_transcribe_job(wav: Path)` — sets busy flag, calls `stt.transcribe(wav)`, if non-empty → `inject_fn(text)` + stop-tick, clears busy flag, restores idle state.
    - IPC `speak` handler: if `tts.enabled` and `response_id` != last spoken id, call `playback.speak(text, response_id)`.
    - IPC `replay` → `playback.replay_last()`.
    - IPC `status` → `{ok: True, playing: bool, stt_provider: str}`.
    - IPC `interrupt` → `playback.interrupt()`.
    - IPC `quit` → wraps `rumps.quit_application()`.
  - `class VoiceDaemon(rumps.App)` — thin shell that constructs a `DaemonCore` with default thread dispatch, wires menu items ("Replay last", "Edit config…"), and updates its title from `_on_state_change`. Icon states: 🎙️ idle, 🔴 recording, ⏳ transcribing, 🔊 playing, ⚠️ error.
  - `run_daemon() -> None` — CLI entry point: loads config + secrets, instantiates `VoiceDaemon`, calls `.run()`.
  - Provider factory helpers: `_make_stt(config, secrets)`, `_make_tts_primary(config, secrets)` — return the configured provider, falling back to `whisper_local`/`say` if the cloud key is missing.

- [ ] **Step 1: Write failing tests**

`tests/test_daemon.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
from claude_voice.config import Config
from claude_voice.hotkey import HotkeyEvent
from claude_voice.daemon import DaemonCore


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
    wav = Path("/tmp/x.wav")
    recorder.stop.return_value = wav
    stt.transcribe.return_value = "hello world"
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    stt.transcribe.assert_called_once_with(wav)
    injector.assert_called_once_with("hello world")


def test_ptt_up_short_recording_no_inject():
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = None  # too short
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    stt.transcribe.assert_not_called()
    injector.assert_not_called()


def test_ptt_up_empty_transcript_no_inject():
    core, recorder, _, stt, _, _, injector = _mk_core()
    recorder.stop.return_value = Path("/tmp/x.wav")
    stt.transcribe.return_value = ""
    core.handle_hotkey(HotkeyEvent.PTT_UP)
    injector.assert_not_called()


def test_ptt_up_while_busy_is_ignored():
    """Overlapping PTT press during transcription plays busy-tick, no new STT."""
    core, recorder, _, stt, _, _, _ = _mk_core()
    # Make STT block so the first PTT_UP stays "busy"
    from threading import Event
    proceed = Event()
    stt.transcribe.side_effect = lambda w: (proceed.wait(0.5), "hi")[1]
    recorder.stop.return_value = Path("/tmp/x.wav")

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
    assert stt.transcribe.call_count == 1


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
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_daemon.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `daemon.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Callable
import threading
import subprocess
import sys

import rumps

from .config import Config, CONFIG_DIR, load_config, secrets as read_secrets
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
            inject_fn=inject,
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
    config = load_config()
    secrets = read_secrets()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    VoiceDaemon(config, secrets).run()
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_daemon.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/daemon.py tests/test_daemon.py
git commit -m "feat(daemon): wire hotkey, recorder, STT, playback, IPC into rumps app"
```

---

## Task 15: CLI

**Files:**
- Create: `src/claude_voice/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `daemon.run_daemon`, `ipc.send_message`, `recorder.Recorder`, `stt` providers, `tts` providers, `config.load_config`, `config.secrets`.
- Produces:
  - `click` group `claude-voice` with commands:
    - `start` — calls `daemon.run_daemon()` (blocking).
    - `stop` — `send_message({"op": "quit"})`; prints ok/not running.
    - `status` — `send_message({"op": "status"})`; prints JSON.
    - `replay` — `send_message({"op": "replay"})`.
    - `test-mic` — records 3 s, runs STT, prints transcript.
    - `test-tts TEXT` — synthesizes and plays TEXT via configured TTS.
  - `def main() -> None` — click entry.

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
from click.testing import CliRunner
from claude_voice.cli import main


def test_stop_when_daemon_not_running(mocker):
    mocker.patch("claude_voice.cli.send_message", return_value=None)
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test_stop_when_daemon_running(mocker):
    mocker.patch("claude_voice.cli.send_message", return_value={"ok": True})
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "stop" in result.output.lower() or "ok" in result.output.lower()


def test_status_prints_json(mocker):
    mocker.patch(
        "claude_voice.cli.send_message",
        return_value={"ok": True, "playing": False},
    )
    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0
    assert "playing" in result.output


def test_replay_sends_op(mocker):
    send = mocker.patch(
        "claude_voice.cli.send_message", return_value={"ok": True}
    )
    result = CliRunner().invoke(main, ["replay"])
    assert result.exit_code == 0
    assert send.call_args.args[0]["op"] == "replay"


def test_test_tts_speaks(mocker):
    mocker.patch("claude_voice.cli.load_config")
    mocker.patch("claude_voice.cli.read_secrets", return_value={
        "DEEPGRAM_API_KEY": None,
        "ELEVENLABS_API_KEY": None,
        "ANTHROPIC_API_KEY": None,
    })
    provider = mocker.MagicMock()
    handle = mocker.MagicMock()
    provider.speak.return_value = handle
    mocker.patch("claude_voice.cli._make_tts_primary", return_value=provider)
    result = CliRunner().invoke(main, ["test-tts", "hello"])
    assert result.exit_code == 0
    provider.speak.assert_called_once_with("hello")
    handle.wait.assert_called()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `cli.py`**

```python
from __future__ import annotations
import json
import time
import click

from .config import load_config, secrets as read_secrets
from .ipc import send_message
from .daemon import run_daemon, _make_stt, _make_tts_primary
from .recorder import Recorder


@click.group()
def main() -> None:
    """Claude Voice — voice plugin for Claude Code."""


@main.command()
def start() -> None:
    """Run the daemon (blocking)."""
    run_daemon()


@main.command()
def stop() -> None:
    """Stop the running daemon."""
    reply = send_message({"op": "quit"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo("stopped")


@main.command()
def status() -> None:
    """Print daemon status as JSON."""
    reply = send_message({"op": "status"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo(json.dumps(reply, indent=2))


@main.command()
def replay() -> None:
    """Replay the last spoken response."""
    reply = send_message({"op": "replay"})
    if reply is None:
        click.echo("daemon not running")
        return
    click.echo("ok" if reply.get("ok") else "nothing to replay")


@main.command("test-mic")
def test_mic() -> None:
    """Record 3 seconds and print the transcript."""
    config = load_config()
    secrets = read_secrets()
    stt = _make_stt(config, secrets)
    rec = Recorder()
    click.echo("recording 3s… speak now")
    rec.start()
    time.sleep(3.0)
    wav = rec.stop()
    if wav is None:
        click.echo("no audio captured")
        return
    click.echo(f"transcribing {wav}…")
    click.echo(stt.transcribe(wav))


@main.command("test-tts")
@click.argument("text")
def test_tts(text: str) -> None:
    """Speak TEXT via the configured TTS provider."""
    config = load_config()
    secrets = read_secrets()
    provider = _make_tts_primary(config, secrets)
    handle = provider.speak(text)
    handle.wait()
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/cli.py tests/test_cli.py
git commit -m "feat(cli): claude-voice start/stop/status/replay/test-mic/test-tts"
```

---

## Task 16: Stop hook

**Files:**
- Create: `src/claude_voice/hook.py`
- Create: `tests/test_hook.py`

**Interfaces:**
- Consumes: `transcript_reader.read_last_assistant`, `text_cleaner.clean_for_tts`, `ipc.send_message`, `config.load_config`, `config.secrets`.
- Produces:
  - `main() -> int` — reads JSON from stdin, extracts `transcript_path`, reads last assistant msg, cleans text, optionally summarizes, sends `{"op":"speak","text":...,"response_id":...}` to daemon via `send_message`. Returns 0 in all normal cases.
  - `summarize(text: str, api_key: str) -> str` — calls Claude Haiku 4.5 to condense. Returns the summary, or the original if the API call fails.
  - Behavior:
    - No transcript path in stdin → exit 0.
    - Transcript file missing / no assistant message → exit 0.
    - Cleaned text empty → exit 0.
    - `config.tts.mode == "summary"` OR `len(text) > 5000` → call `summarize` if `ANTHROPIC_API_KEY` present; otherwise use raw text.
    - `len(text) > config.tts.summary_threshold` (default 500) → summarize if key present.
    - Daemon not running → append to `hook.log`, exit 0.

- [ ] **Step 1: Write failing tests**

`tests/test_hook.py`:
```python
import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from claude_voice.hook import main


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
    mocker.patch("claude_voice.hook.load_config")
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
    mocker.patch("claude_voice.hook.load_config")
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
    mocker.patch("claude_voice.hook.load_config")
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
    mocker.patch("claude_voice.hook.load_config")
    mocker.patch(
        "claude_voice.hook.read_secrets",
        return_value={"ANTHROPIC_API_KEY": None},
    )
    _run_with_stdin(
        {"hook_event_name": "Stop", "transcript_path": str(jsonl)}, mocker
    )
    assert log_path.exists()
    assert "daemon offline" in log_path.read_text()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_hook.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `hook.py`**

```python
from __future__ import annotations
from pathlib import Path
import json
import sys
from datetime import datetime

from .config import CONFIG_DIR, load_config, secrets as read_secrets
from .transcript_reader import read_last_assistant
from .text_cleaner import clean_for_tts
from .ipc import send_message

HOOK_LOG_PATH = CONFIG_DIR / "hook.log"


def _log(msg: str) -> None:
    try:
        HOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HOOK_LOG_PATH, "a") as fp:
            fp.write(f"{datetime.utcnow().isoformat()} {msg}\n")
    except Exception:
        pass


def summarize(text: str, api_key: str) -> str:
    """Condense a long response into 1-2 spoken sentences via Claude Haiku."""
    try:
        from anthropic import Anthropic
    except ImportError:
        return text
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize the following in 1-2 short spoken sentences. "
                    "No markdown, no code, plain speech only:\n\n" + text
                ),
            }],
        )
        block = resp.content[0]
        return getattr(block, "text", text) or text
    except Exception as e:
        _log(f"summarize failed: {e}")
        return text


def _should_summarize(text: str, config) -> bool:
    if config.tts.mode == "summary":
        return True
    if len(text) > 5000:
        return True
    if len(text) > config.tts.summary_threshold:
        return True
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0

    msg = read_last_assistant(Path(transcript_path))
    if msg is None:
        return 0

    cleaned = clean_for_tts(msg.content)
    if not cleaned:
        return 0

    config = load_config()
    secrets = read_secrets()

    text = cleaned
    if _should_summarize(cleaned, config):
        api_key = secrets.get("ANTHROPIC_API_KEY")
        if api_key:
            text = summarize(cleaned, api_key)

    reply = send_message({
        "op": "speak",
        "text": text,
        "response_id": msg.id,
    })
    if reply is None:
        _log(f"daemon offline; skipped speaking msg_id={msg.id}")
    return 0
```

- [ ] **Step 4: Run tests — expect all pass**

Run: `pytest tests/test_hook.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hook.py tests/test_hook.py
git commit -m "feat(hook): stop hook reads transcript, cleans, sends to daemon"
```

---

## Task 17: Install script

**Files:**
- Create: `install.sh`
- Create: `src/claude_voice/_install.py` (helper for merging settings.json — testable)
- Create: `tests/test_install.py`

**Interfaces:**
- `_install.merge_stop_hook(settings: dict, command: str = "claude-voice-hook") -> dict` — returns a new settings dict with the Stop hook registered idempotently. Preserves any existing hooks. Dedupes by exact `command` string.
- `install.sh` — top-level shell script:
  1. Check Python >= 3.11
  2. `pip install -e .` in the current repo
  3. Create `~/.config/claude-voice/` if missing
  4. Copy `config.yaml.example` → `~/.config/claude-voice/config.yaml` if not present
  5. Copy `env.example` → `~/.config/claude-voice/.env` if not present
  6. Run `python -m claude_voice._install merge-settings` — merges the Stop-hook entry into `~/.claude/settings.json` (creates if missing)
  7. Print next-step instructions

- [ ] **Step 1: Write failing test for merger**

`tests/test_install.py`:
```python
from claude_voice._install import merge_stop_hook


def test_merge_into_empty_settings():
    out = merge_stop_hook({})
    assert out["hooks"]["Stop"][0]["hooks"][0]["command"] == "claude-voice-hook"


def test_merge_preserves_unrelated_settings():
    settings = {"other": "value", "hooks": {"PreToolUse": [{"matcher": "*"}]}}
    out = merge_stop_hook(settings)
    assert out["other"] == "value"
    assert out["hooks"]["PreToolUse"] == [{"matcher": "*"}]
    assert "Stop" in out["hooks"]


def test_merge_is_idempotent():
    settings = {}
    once = merge_stop_hook(settings)
    twice = merge_stop_hook(once)
    stop_entries = twice["hooks"]["Stop"]
    all_commands = [
        h["command"]
        for entry in stop_entries
        for h in entry.get("hooks", [])
    ]
    assert all_commands.count("claude-voice-hook") == 1


def test_merge_preserves_other_stop_hooks():
    settings = {"hooks": {"Stop": [
        {"matcher": "", "hooks": [{"type": "command", "command": "other-tool"}]}
    ]}}
    out = merge_stop_hook(settings)
    all_commands = [
        h["command"]
        for entry in out["hooks"]["Stop"]
        for h in entry.get("hooks", [])
    ]
    assert "other-tool" in all_commands
    assert "claude-voice-hook" in all_commands
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_install.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_install.py`**

```python
from __future__ import annotations
import json
from pathlib import Path
import sys


def merge_stop_hook(settings: dict, command: str = "claude-voice-hook") -> dict:
    settings = dict(settings)
    hooks = dict(settings.get("hooks") or {})
    stop_list = list(hooks.get("Stop") or [])
    # dedupe by command
    for entry in stop_list:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                hooks["Stop"] = stop_list
                settings["hooks"] = hooks
                return settings
    stop_list.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    })
    hooks["Stop"] = stop_list
    settings["hooks"] = hooks
    return settings


def _cli() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "merge-settings":
        print("usage: python -m claude_voice._install merge-settings", file=sys.stderr)
        return 2
    path = Path.home() / ".claude" / "settings.json"
    if path.exists():
        with open(path) as fp:
            data = json.load(fp)
    else:
        data = {}
    merged = merge_stop_hook(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fp:
        json.dump(merged, fp, indent=2)
    print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
```

- [ ] **Step 4: Run merge tests — expect all pass**

Run: `pytest tests/test_install.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write `install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

echo ">> Checking Python 3.11+"
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'

echo ">> Installing package (editable)"
python3 -m pip install -e ".[dev]"

CFG_DIR="$HOME/.config/claude-voice"
mkdir -p "$CFG_DIR"

if [ ! -f "$CFG_DIR/config.yaml" ]; then
    cp config.yaml.example "$CFG_DIR/config.yaml"
    echo ">> Wrote $CFG_DIR/config.yaml"
fi
if [ ! -f "$CFG_DIR/.env" ]; then
    cp env.example "$CFG_DIR/.env"
    echo ">> Wrote $CFG_DIR/.env — add your API keys here"
fi

echo ">> Merging Stop hook into ~/.claude/settings.json"
python3 -m claude_voice._install merge-settings

cat <<'EOF'

============================================================
Install complete. Next steps:

1. Add your API keys in ~/.config/claude-voice/.env
2. Start the daemon:  claude-voice start
3. Grant Microphone and Accessibility permissions when prompted
4. To auto-start on login: System Settings → General → Login Items
   → add "claude-voice" (or run `claude-voice start` at login)
============================================================
EOF
```

- [ ] **Step 6: Make executable**

Run: `chmod +x install.sh`

- [ ] **Step 7: Verify install script structure (dry run)**

Run: `bash -n install.sh` — expect no syntax errors.

- [ ] **Step 8: Commit**

```bash
git add install.sh src/claude_voice/_install.py tests/test_install.py
git commit -m "feat(install): script + idempotent settings.json merger"
```

---

## Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Verify all entry points install cleanly**

Run:
```bash
pip install -e ".[dev]"
which claude-voice
which claude-voice-hook
claude-voice --help
```

Expected: both binaries exist; help prints.

- [ ] **Step 3: Manual E2E smoke test (README-driven)**

Add to README:
```
## Manual smoke test

1. Set API keys in ~/.config/claude-voice/.env
2. `claude-voice start` in one terminal
3. Grant Microphone + Accessibility permissions when prompted
4. `claude-voice test-mic` in another terminal — speak, check transcript
5. `claude-voice test-tts "hello world"` — hear a voice
6. Open a Claude Code session, ask any question, wait for response,
   verify TTS speaks the prose portion
7. Hold Right Option, speak an instruction, release — text should
   appear in the terminal
```

- [ ] **Step 4: Final commit if anything changed**

```bash
git add README.md
git commit -m "docs: add manual smoke test steps" || echo "no changes"
```
