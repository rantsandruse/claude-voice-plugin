# Claude Voice

A macOS voice plugin for Claude Code.

- **Push-to-talk speech-to-text (STT)** — hold a hotkey, speak an instruction, release; the transcript is pasted into whatever terminal is focused.
- **Text-to-speech (TTS)** — when Claude finishes a response, the prose portion is spoken back to you.

Runs as a lightweight menu-bar app on macOS. Works with an unmodified `claude` CLI (no wrapper, no launcher).

## Requirements

- macOS 14+ (Sonoma or later)
- Python 3.11+
- ~500 MB free disk space (for the Whisper `small` model, downloaded on first use)
- Optional: API keys for [Deepgram](https://deepgram.com) (STT) and/or [ElevenLabs](https://elevenlabs.io) (TTS) if you want cloud quality

## Install

```bash
git clone <this repo>
cd claude-voice-plugin
./install.sh
```

This will:
1. Install the Python package into a venv
2. Create `~/.config/claude-voice/config.yaml` and `.env` from templates
3. Register a `Stop` hook in `~/.claude/settings.json` so Claude Code invokes TTS when a response finishes

## Grant macOS Permissions (required)

The daemon needs two permissions to work. Grant them **before** first use — the first PTT attempt otherwise crashes or silently fails.

### 1. Accessibility (required for paste)

The daemon uses `osascript` to send `⌘V` into the focused terminal. macOS blocks this by default.

- Open **System Settings → Privacy & Security → Accessibility**
- Click **+**, press **⌘⇧G** in the file picker to paste a hidden path
- Add all three of these paths (order matters — Terminal first has the highest hit rate):
  1. `/System/Applications/Utilities/Terminal.app` — or `/Applications/iTerm.app` if you use iTerm2
  2. `/opt/homebrew/bin/python3` (or wherever your Python actually lives — see note below)
  3. `<repo>/.venv/bin/python`
- Toggle each **on**

**Shortcut to open the pane directly:**
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

**Find your real Python path** (venv symlinks resolve to the underlying interpreter):
```bash
readlink -f "$(pwd)/.venv/bin/python"
```

### 2. Microphone (required for STT)

macOS will prompt automatically the first time you press PTT. Grant it to the same terminal / Python you added to Accessibility.

If the prompt doesn't appear:
- System Settings → Privacy & Security → **Microphone**
- Toggle Terminal/iTerm and Python on

## Configure

Edit `~/.config/claude-voice/config.yaml`:

```yaml
hotkey:
  ptt: "alt_r"                # Right Option by default. Also: alt_l, cmd_r, f1..f12

stt:
  provider: "whisper_local"   # or "deepgram" for cloud
  whisper_local:
    model: "small"            # tiny | base | small | medium | large-v3

tts:
  enabled: true
  provider: "say"             # or "elevenlabs" for cloud
  mode: "prose"               # or "summary" (uses Claude Haiku to condense long responses)
  summary_threshold: 500      # chars; above this always summarize
  elevenlabs:
    voice_id: "21m00Tcm4TlvDq8ikWAM"  # Rachel — must be a real ElevenLabs ID, not a name
  say:
    voice: "Ava (Premium)"    # see "Voices" below
```

Put API keys in `~/.config/claude-voice/.env`:
```
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
ANTHROPIC_API_KEY=...   # only needed for summary mode
```

## Voices (`say` provider)

macOS ships with several tiers of TTS voices — all free, all offline:

| Tier | Quality | Size | Examples |
|------|---------|------|----------|
| Default | Robotic | preinstalled | Samantha, Alex, Fred |
| Enhanced | Better neural | ~150 MB | Ava (Enhanced), Samantha (Enhanced) |
| Premium | Siri-quality | ~400 MB | **Ava (Premium)**, Zoe (Premium), Evan (Premium) |

**Install Premium voices** (recommended):
1. System Settings → **Accessibility → Spoken Content**
2. Click **System Voice** → **Manage Voices…**
3. Expand **English (United States)** (or your locale)
4. Scroll to the bottom, find voices marked **(Premium)**
5. Click the download arrow — takes ~30 seconds
6. Preview them right there in the panel

**Preview from terminal** (once installed):
```bash
say -v "Ava (Premium)" "This is a sample of the Ava premium voice."
```

**List every voice on your system:**
```bash
say -v '?' | grep en_US
```

**ElevenLabs note:** if you use `provider: "elevenlabs"`, the free tier only allows API access to voices you've generated or cloned yourself — library voices (Rachel, Adam, etc.) require a paid plan. List your usable voices with:
```bash
curl -s https://api.elevenlabs.io/v1/voices \
  -H "xi-api-key: $(grep ELEVENLABS_API_KEY ~/.config/claude-voice/.env | cut -d= -f2)" \
  | python3 -c "
import json,sys
for v in json.load(sys.stdin)['voices']:
    print(f\"{v['category']:12} {v['voice_id']}  {v['name']}\")"
```

## Usage

**Start the daemon** (blocking; adds a 🎙️ icon to your menu bar):
```bash
source .venv/bin/activate
claude-voice start
```

To auto-start on login: **System Settings → General → Login Items** → add `claude-voice`.

**Push-to-talk** (from any focused text field):
- Hold **Right Option** (⌥ on the right of the space bar)
- Speak
- Release
- Transcript is pasted into the focused window

Menu-bar icon state indicates what's happening:
- 🎙️ idle
- 🔴 recording
- ⏳ transcribing
- 🔊 playing TTS
- ⚠️ error

**Interrupt playing TTS:** press the PTT hotkey. Whatever's playing stops and recording begins.

## CLI

```bash
claude-voice start          # run the daemon (blocking)
claude-voice stop           # stop the daemon
claude-voice status         # print daemon state
claude-voice replay         # re-speak the last response
claude-voice test-mic       # record 3s, print the transcript
claude-voice test-tts "hi"  # speak a phrase via the configured provider
```

## Smoke Test

Run these in order after install:

```bash
source .venv/bin/activate

# 1. Verify TTS works
claude-voice test-tts "hello from claude voice"

# 2. Verify STT works (will prompt for mic permission on first run)
claude-voice test-mic          # first run downloads the Whisper model, ~30s

# 3. Start the daemon
claude-voice start             # blocks; look for 🎙️ in menu bar

# 4. In a second terminal, run Claude Code
claude
# Ask any short question. When Claude finishes, you should hear the response.

# 5. In any focused text field, hold Right Option, speak "list files", release.
# Text should paste. Hit Enter to send.
```

## Troubleshooting

**No menu bar icon appears after `claude-voice start`**
- Check the daemon is actually running: `claude-voice status` in another terminal. If it returns JSON, the daemon is alive but the icon didn't register — try `claude-voice stop && claude-voice start`.
- Multiple monitors: the icon shows on the active display's menu bar only.
- Menu bar full / notch: mouse to top-right, or hide other icons.

**PTT does nothing / "osascript is not allowed to send keystrokes"**
- Accessibility permission not granted. Follow the Permissions section above.
- After granting, fully quit Terminal (⌘Q) and restart the daemon.

**Segmentation fault on first PTT press (macOS 14+)**
- Known `sounddevice` / `portaudio` interaction. Should be fixed by the built-in Recorder patch. If it persists, run the daemon in-line to get a Python traceback:
  ```bash
  python -c "from claude_voice.daemon import run_daemon; run_daemon()"
  ```
- Crash logs at `~/Library/Logs/DiagnosticReports/python3.12-*.ips`

**TTS never fires when Claude finishes a response**
- Check `~/.config/claude-voice/hook.log`. If it says `daemon offline`, start the daemon.
- If the log is empty, the Stop hook isn't registered — re-run `install.sh`.
- Verify `~/.claude/settings.json` contains a Stop hook entry pointing to `claude-voice-hook`.

**ElevenLabs returns 404 "voice_not_found"**
- The `voice_id` must be a real ElevenLabs ID (opaque alphanumeric string like `21m00Tcm4TlvDq8ikWAM`), not a voice name.

**ElevenLabs returns 401 "paid_plan_required"**
- Free ElevenLabs plan can't use library voices via API. Either upgrade, use a voice you cloned/generated yourself, or switch `tts.provider` to `"say"`.

**Whisper transcription mangles technical terms**
- Expected on the local model. Options:
  - Bump `stt.whisper_local.model` from `small` to `medium` (better accuracy, more RAM).
  - Switch to Deepgram: `stt.provider: "deepgram"` + set `DEEPGRAM_API_KEY` in `.env`.

## Architecture

Two independent processes:

1. **Daemon** (menu-bar app) — global PTT hotkey → `sounddevice` capture → Whisper/Deepgram → clipboard paste. Owns TTS playback so the next PTT press can interrupt it.
2. **Stop hook** (invoked by Claude Code) — reads the last assistant message from the transcript, cleans it (strips code blocks, file paths, markdown), optionally summarizes, sends it to the daemon over a Unix socket for playback.

Communication over a Unix domain socket at `~/.config/claude-voice/daemon.sock`.

Design details: `docs/superpowers/specs/2026-07-30-voice-plugin-design.md`
