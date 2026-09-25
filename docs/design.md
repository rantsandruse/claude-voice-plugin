# Voice Plugin for Claude Code — Design

**Date:** 2026-07-30
**Status:** Draft for implementation

## Goal

Let the user drive Claude Code by voice on macOS:

- **STT (input):** hold a push-to-talk hotkey, speak an instruction, release; the transcript is inserted into the focused Claude Code terminal as if typed.
- **TTS (output):** when Claude Code finishes a response, the natural-language portion is spoken aloud through a high-quality voice.

Both directions must work with an unmodified `claude` CLI. The user should not need a special launcher or terminal wrapper.

## Non-goals

- **Not a PTY wrapper.** We do not proxy Claude Code's terminal I/O.
- **Not always-on.** No wake word, no continuous listening.
- **Not multi-platform (yet).** macOS only. Linux/Windows are future work.
- **Not a general dictation tool.** The daemon happens to type into whatever's focused, but the design assumes the target is a terminal running Claude Code.
- **No true TTS pause/resume.** Interrupted TTS can be replayed from the start; mid-utterance resume is out of scope.

## Architecture

Two independent processes that communicate over a Unix domain socket:

```
┌──────────────────────────────────────────────────────────┐
│ 1. VOICE DAEMON (macOS menu bar app, Python 3.11+)       │
│    - Global PTT hotkey listener (pynput)                 │
│    - Audio capture (sounddevice, 16kHz mono int16)       │
│    - STT provider (faster-whisper local / Deepgram)      │
│    - Text delivery (clipboard + ⌘V, restore clipboard)   │
│    - Menu bar UI (rumps): idle → recording → transcribing│
│    - TTS playback controller (owns audio subprocess)     │
│    - Unix socket server for hook messages                │
│    - CLI: start/stop/status/replay                       │
└──────────────────────────────────────────────────────────┘
                          │
                 [types transcript into
                  focused terminal window]
                          ▼
                  ┌───────────────┐
                  │  Claude Code  │  (unmodified)
                  └───────┬───────┘
                          │
                 [Stop event fires when
                  response completes]
                          ▼
┌──────────────────────────────────────────────────────────┐
│ 2. STOP HOOK (Python entry point invoked by Claude)      │
│    - Registered in ~/.claude/settings.json               │
│    - Reads last assistant message from transcript JSONL  │
│    - Cleans text: strips code, tool calls, markdown      │
│    - Optionally summarizes for long responses            │
│    - Sends "speak this" over Unix socket to daemon       │
└──────────────────────────────────────────────────────────┘
```

### Why two processes

- **STT is inherently OS-level.** It needs a global hotkey and a way to insert text into any terminal. A daemon does that.
- **TTS is inherently Claude-level.** It needs to know when a response completes and what it said. Claude Code's `Stop` hook gives us both natively.
- **A single PTY wrapper would have to correctly proxy Claude Code's raw-mode TUI** (ANSI redraws, mouse events, resize). High fragility, no benefit over two focused pieces.
- **Pure plugin/hook approach can't do STT** — there is no Claude Code hook that injects text into the input buffer.

### Why the daemon owns TTS playback

The hook could call TTS itself, but the daemon needs to interrupt playback on the next PTT press (Q8 decision). Centralizing playback in the daemon keeps interrupt logic in one place; the hook just publishes "speak this text" messages.

## Component 1: Voice Daemon

### Runtime

- Python 3.11+
- `rumps.App` subclass, main-thread event loop for the menu bar
- Background threads for the hotkey listener and audio capture
- A single-worker thread pool for STT jobs (only one transcription at a time)

### Hotkey listener

- `pynput.keyboard.Listener` in a background thread
- Watches the configured PTT key (default: Right Option = `Key.alt_r`)
- Events posted to the daemon:
  - `START_RECORDING` on PTT key down
  - `STOP_RECORDING` on PTT key up
  - `INTERRUPT_TTS` on PTT key down while TTS is playing
- Any other key does **not** interrupt TTS (per Q8 decision).

### Audio recorder

- `sounddevice.InputStream`, 16 kHz mono int16 (whisper's native format)
- Ring buffer; capture starts on `START_RECORDING`, stops on `STOP_RECORDING`
- Writes a WAV file to `/tmp/claude-voice/<timestamp>.wav`
- Recordings shorter than 300 ms are discarded (avoids garbage from accidental taps)

### STT dispatcher

- `stt/whisper_local.py` — loads a `faster-whisper` model on first use, keeps it resident. Default model `small`; configurable `tiny | base | small | medium | large-v3`.
- `stt/deepgram.py` — HTTPS POST to Deepgram, `nova-2` model
- Selected by `config.stt.provider` (default `whisper_local`)
- Returns a cleaned transcript: strip trailing period, normalize whitespace, filter whisper hallucination phrases ("Thanks for watching", "you", etc.)
- On empty transcript → discard, no injection

### Text injector (clipboard + paste with restore)

```python
def inject(text: str) -> None:
    saved = subprocess.check_output(["pbpaste"])
    subprocess.run(["pbcopy"], input=text.encode())
    osascript('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.15)  # let paste land
    subprocess.run(["pbcopy"], input=saved)
```

Rationale (Q5): simulated typing is slow and drops keys; plain clipboard clobbers the user's clipboard. Save-and-restore is B's speed with A's harmlessness. Edge case: if the user copies something during the ~200 ms window, restore overwrites it. Accepted.

Non-text clipboard content (image, file reference) → skip restore, log a warning.

### TTS playback controller

- Owns a `subprocess.Popen` handle for the currently playing audio:
  - ElevenLabs: `afplay -` fed by streamed MP3 chunks
  - macOS `say`: `subprocess.Popen(["say", text])`
- Receives `{"op": "speak", "text": "...", "response_id": "..."}` from the socket
- Kills the running subprocess on `INTERRUPT_TTS`
- Stores the last-spoken text keyed by `response_id`; `claude-voice replay` re-plays it from the start

### Menu bar UI (rumps)

- Icon states:
  - 🎙️ idle
  - 🔴 recording
  - ⏳ transcribing
  - 🔊 playing TTS
  - ⚠️ error (mic denied, provider down, etc.)
- Menu items:
  - `Recording sounds ☑` (toggle; syncs to config)
  - `TTS enabled ☑` (toggle)
  - `Replay last`
  - `Edit config…` (opens `~/.config/claude-voice/config.yaml` in `$EDITOR`)
  - `Quit`
- Error notifications via `rumps.notification()` for terminal-visible failures.

### CLI (`claude-voice` entry point)

- `claude-voice start` — launches the rumps app (blocking; used by Login Items)
- `claude-voice stop` — sends `{"op": "quit"}` over the socket
- `claude-voice status` — prints daemon PID, current state, active STT/TTS providers
- `claude-voice replay` — sends `{"op": "replay"}`
- `claude-voice test-mic` — records 3 s, runs STT, prints transcript
- `claude-voice test-tts "hello"` — synthesizes and plays a phrase through the configured provider

### IPC

- Unix domain socket at `~/.config/claude-voice/daemon.sock`
- Line-delimited JSON, one message per line
- Server (daemon) accepts multiple concurrent clients (hook + CLI). Handlers dispatch on `op`:
  - `speak` — enqueue for TTS playback
  - `replay` — replay last-spoken text
  - `status` — return state JSON
  - `quit` — shut down daemon

## Component 2: Stop Hook

### Registration

In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "claude-voice-hook" }
        ]
      }
    ]
  }
}
```

The installer merges this entry idempotently — it dedupes by exact command string, does not overwrite unrelated hook entries.

### Hook script (`claude-voice-hook`)

Claude Code invokes the command with hook context on stdin:

```json
{
  "hook_event_name": "Stop",
  "session_id": "...",
  "transcript_path": "/Users/.../projects/<slug>/<session>.jsonl",
  "stop_hook_active": false
}
```

Flow:

1. **Read** the transcript JSONL, walk backward to find the last `{"role": "assistant", ...}` entry. Extract its `content` and its message id (used as `response_id`).
2. **Clean** the content through `text_cleaner.py`:
   - Strip fenced code blocks (```…```) and inline code (`…`)
   - Strip markdown emphasis, headings, list bullets — keep the text
   - Replace bare file paths (regex `[/\w\-.]+\.\w{1,5}`) with "a file"
   - Drop tool-use blocks entirely
   - Collapse multiple newlines, trim whitespace
   - If the result is empty → exit 0 silently
3. **Optionally summarize** (only if `config.tts.mode == "summary"` OR length > `config.tts.summary_threshold`):
   - Call `claude-haiku-4-5` via the Anthropic SDK: "Summarize this response in 1-2 spoken sentences. No markdown."
   - Cache the result keyed by `sha256(text)`; replay does not re-summarize.
4. **Send** to the daemon over the Unix socket:
   ```json
   {"op": "speak", "text": "...", "response_id": "<msg_id>"}
   ```
5. If the daemon isn't running → write to `~/.config/claude-voice/hook.log` and exit 0. Claude Code proceeds normally; there is no user-visible failure.
6. **Idempotency:** the daemon tracks the last-spoken `response_id`. If `Stop` fires twice for the same message, the second call is a no-op.

### Failure modes

- Transcript file missing → exit 0
- TTS provider errors (network, quota) → daemon falls back to `say`, notifies via menu bar
- Text cleaner produces empty string → skip speaking
- Very long response (>5000 chars) → auto-force summary mode for this response, regardless of config

## Configuration

**Location:** `~/.config/claude-voice/config.yaml`. Missing keys fall back to defaults defined in `config.py`.

**Schema:**

```yaml
hotkey:
  ptt: "alt_r"                # pynput key name
  replay: "cmd+shift+r"       # optional; CLI still works without this

stt:
  provider: "whisper_local"   # whisper_local | deepgram
  whisper_local:
    model: "small"            # tiny | base | small | medium | large-v3
    device: "auto"            # auto | cpu | cuda | mps
    language: "en"
  deepgram:
    model: "nova-2"

tts:
  enabled: true
  provider: "elevenlabs"      # elevenlabs | say
  mode: "prose"               # prose | summary
  summary_threshold: 500      # chars; above this always summarize
  elevenlabs:
    voice_id: "rachel"
    model: "eleven_turbo_v2_5"
  say:
    voice: "Samantha"

feedback:
  sounds: true                # start/stop/error ticks
  menu_bar: true

logging:
  level: "info"
  path: "~/.config/claude-voice/daemon.log"
```

**Secrets** — env vars loaded from `~/.config/claude-voice/.env` (never in `config.yaml`):

```
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
ANTHROPIC_API_KEY=...   # only if summary mode is enabled
```

## Project layout

```
voice_plugin/
├── pyproject.toml                 # package metadata, entry points
├── README.md
├── install.sh                     # sets up hook, config, .env templates
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-07-30-voice-plugin-design.md
├── src/claude_voice/
│   ├── __init__.py
│   ├── daemon.py                  # rumps App, event loop
│   ├── cli.py                     # `claude-voice` entry point
│   ├── hook.py                    # `claude-voice-hook` entry point
│   ├── config.py                  # YAML loader, env overrides, schema, defaults
│   ├── ipc.py                     # Unix socket client + server
│   ├── inject.py                  # clipboard paste with restore
│   ├── hotkey.py                  # pynput listener
│   ├── recorder.py                # sounddevice capture
│   ├── text_cleaner.py            # strip code, paths, markdown
│   ├── transcript_reader.py       # read last assistant msg from JSONL
│   ├── stt/
│   │   ├── base.py                # STTProvider protocol
│   │   ├── whisper_local.py
│   │   └── deepgram.py
│   └── tts/
│       ├── base.py                # TTSProvider protocol
│       ├── elevenlabs.py
│       └── say.py
└── tests/
    ├── test_text_cleaner.py       # many fixtures of real Claude Code responses
    ├── test_config.py
    ├── test_transcript_reader.py
    └── test_inject.py             # mocks pbcopy/pbpaste
```

### Package entry points (`pyproject.toml`)

```toml
[project.scripts]
claude-voice = "claude_voice.cli:main"
claude-voice-hook = "claude_voice.hook:main"
```

## Install flow

`install.sh`:

1. Verify Python 3.11+ available
2. `pip install -e .` in the repo
3. Create `~/.config/claude-voice/` if missing
4. Copy `config.yaml` template if none exists (does not overwrite an existing config)
5. Copy `.env` template if none exists
6. Merge Stop-hook entry into `~/.claude/settings.json` (idempotent — no-op if already registered)
7. Print instructions:
   - "Grant Microphone and Accessibility permissions to Terminal/iTerm when prompted"
   - "Add Claude Voice to System Settings → General → Login Items to auto-start"
   - "Set your API keys in `~/.config/claude-voice/.env`"

## Testing strategy

- **Unit tests (fast, mocked):**
  - `text_cleaner` — many fixtures of real Claude Code responses (code-heavy, prose-heavy, tool-use, mixed)
  - `config` — schema defaults, env overrides, malformed YAML
  - `transcript_reader` — malformed lines, multi-message transcripts, missing file
  - `inject` — mocked subprocess for `pbcopy`/`pbpaste`/`osascript`
- **Provider tests:**
  - Recorded WAV fixtures for STT providers
  - VCR-style HTTP mocks for Deepgram, ElevenLabs
- **Manual E2E** checklist in README (real microphone, real Claude Code). E2E automation is not worth building for a personal tool.
- OS-level primitives (`osascript`, `pbcopy`) are exercised in dev testing directly, not mocked in E2E.

## Edge cases & error handling

| Situation | Behavior |
|-----------|----------|
| PTT press <300 ms | Discard recording, no STT call |
| Whisper hallucinates on silence ("Thanks for watching") | Filter list matches → skip inject |
| `pbpaste` returns non-text (image, file) | Skip clipboard restore, log warning |
| Multiple PTTs during transcription | Queue max 1, drop extras with a "busy" tick |
| Daemon dies while TTS playing | Hook still logs; user restarts daemon; in-flight audio lost, no other state |
| Multiple Claude Code sessions running | All Stop hooks target the same daemon; the most recent response interrupts prior TTS |
| No mic permission | Menu bar shows ⚠️; clicking opens System Settings → Privacy → Microphone |
| No accessibility permission (for keystroke) | Same handling; opens System Settings → Privacy → Accessibility |
| TTS provider network error | Fall back to `say`, notify via menu bar |
| Response >5000 chars | Force summary mode regardless of config |
| Empty cleaned text (all code) | Skip speaking silently |

## Open questions / future work (explicitly out of scope for v1)

- Linux/Windows support
- Custom whisper vocabulary / biasing on user's codebase identifiers
- Wake word ("Hey Claude") as an alternative trigger
- True TTS pause/resume with position tracking
- Multi-language support (config supports `language:` but only tested with English)
- Per-project config overrides
