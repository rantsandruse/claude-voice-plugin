# Claude Voice

A macOS voice plugin for Claude Code — talk to Claude, hear it back.

- **Push-to-talk STT** — hold a hotkey, speak, release. The transcript pastes into your focused terminal.
- **Spoken responses** — Claude's answer is read aloud when the turn ends. Configurable summary or verbatim.
- **Ambient audio feedback** — ticks and interim narration through Claude Code's `UserPromptSubmit` / `PreToolUse` / `Stop` hooks so you can follow along without looking at the screen.

Runs as a lightweight menu-bar app. Works with an unmodified `claude` CLI (no wrapper, no fork).

## Quick Start

```bash
git clone <this repo>
cd claude-voice-plugin
./install.sh

# Summary mode is the default — add your Anthropic API key so the Stop hook can call Haiku.
# (If you'd rather not, set tts.mode: "prose" in ~/.config/claude-voice/config.yaml and skip this.)
echo "ANTHROPIC_API_KEY=sk-ant-..." >> ~/.config/claude-voice/.env

# Start the daemon — blocks the terminal and leaves 🎙️ in your menu bar
claude-voice start
```

Then, in any focused text field:

1. Hold **Right Option**, speak, release. The transcript pastes and auto-submits.
2. Wait for Claude's answer — you'll hear a Ping when it starts thinking, a Purr for each tool it runs, and a spoken summary when it's done.

**One-time permissions.** macOS will prompt for **Microphone** access on your first PTT press. Grant **Accessibility** to Terminal (or iTerm) *and* your Python interpreter before the first PTT — full details in [Grant macOS Permissions](#grant-macos-permissions-required) below.

Everything after this point in the README is reference material — skim as needed.

## Requirements

- macOS 14+ (Sonoma or later)
- Python 3.11+
- ~500 MB free disk space (for the Whisper `small` model, downloaded on first use)
- **`ANTHROPIC_API_KEY`** — required if you use summary mode (the default). Every response goes through Claude Haiku before being spoken. Skip only if you switch to `tts.mode: "prose"`.
- Optional: API keys for [Deepgram](https://deepgram.com) (STT) and/or [ElevenLabs](https://elevenlabs.io) (TTS) if you want cloud quality

## Install

```bash
git clone <this repo>
cd claude-voice-plugin
./install.sh
```

This will:
1. Install the Python package into whatever `python3` resolves to on your PATH (system Python, conda, an already-activated venv — all fine). The installer does **not** create a venv for you; if you want isolation, activate one before running `./install.sh`.
2. Create `~/.config/claude-voice/config.yaml` and `.env` from templates
3. Register three hooks in `~/.claude/settings.json` so Claude Code drives the voice layer:
   - `Stop` — speak the assistant's response when the turn ends
   - `PreToolUse` — heartbeat + interim narration for each tool call
   - `UserPromptSubmit` — audible confirmation when Claude receives your prompt
   All three point at the absolute path of `claude-voice-hook` (resolved via `shutil.which()` at install time), so Claude Code's non-interactive hook environment can find the binary regardless of PATH.

## Grant macOS Permissions (required)

The daemon needs two permissions to work. Grant them **before** first use — the first PTT attempt otherwise crashes or silently fails.

### 1. Accessibility (required for paste)

The daemon uses `osascript` to send `⌘V` into the focused terminal. macOS blocks this by default.

- Open **System Settings → Privacy & Security → Accessibility**
- Click **+**, press **⌘⇧G** in the file picker to paste a hidden path
- Add these paths (Terminal first has the highest hit rate):
  1. `/System/Applications/Utilities/Terminal.app` — or `/Applications/iTerm.app` if you use iTerm2
  2. The Python interpreter you installed the package into. Find it with `which python3` on the same shell you ran `./install.sh` in — common results: `/opt/homebrew/bin/python3`, `/opt/anaconda3/bin/python3`, or a venv's `bin/python3` if you activated one.
- Toggle each **on**

**Shortcut to open the pane directly:**
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

**Find your real Python path** (symlinks resolve to the underlying interpreter):
```bash
readlink -f "$(which python3)"
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
  provider: "whisper_local"   # whisper_local (default, offline) | deepgram (cloud, needs DEEPGRAM_API_KEY)
  whisper_local:
    model: "small"            # tiny | base | small | medium | large-v3

tts:
  enabled: true
  provider: "say"             # say (default, offline, macOS built-in) | elevenlabs (cloud, needs ELEVENLABS_API_KEY)
  mode: "summary"             # summary (default) — every response goes through Claude Haiku for a spoken 1-2 sentences.
                              # prose — speak verbatim; still auto-summarizes above summary_threshold.
                              # Say "verbatim" (PTT + the single word) to override for the very next response.
  summary_threshold: 500      # chars; above this always summarize (even in prose mode)
  min_summarize_chars: 200    # chars; below this always speak verbatim, skipping Haiku even in summary mode.
                              # Prevents paraphrase mismatch on short answers and cuts ~500ms of latency.
  max_duration: 60            # seconds; hard cap on any TTS subprocess. Prevents wedged say/afplay from blocking future PTT.
  elevenlabs:
    voice_id: "21m00Tcm4TlvDq8ikWAM"  # Rachel — must be a real ElevenLabs ID, not a name
  say:
    voice: "Ava (Premium)"    # see "Voices" below
```

Put API keys in `~/.config/claude-voice/.env`:
```
DEEPGRAM_API_KEY=...     # optional: only needed if you set stt.provider: "deepgram"
ELEVENLABS_API_KEY=...   # optional: only needed if you set tts.provider: "elevenlabs"
ANTHROPIC_API_KEY=...    # needed for summary mode (default). Skip only if you set tts.mode: "prose".
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
claude-voice start
```

The daemon preloads the Whisper model at startup so the first PTT press feels the same as the tenth. Startup blocks ~2 seconds on the model load. To auto-start on login: **System Settings → General → Login Items** → add `claude-voice`.

Push-to-talk basics are in the [Quick Start](#quick-start). What follows are the voice-controlled and ambient behaviors that build on it.

**Interrupt playing TTS:** press the PTT hotkey while Claude is speaking. Playback stops and recording starts immediately. (For a force-kill from the terminal when PTT itself isn't reaching the daemon, see `claude-voice interrupt` in the [CLI](#cli) section.)

### Voice commands

Some utterances are intercepted as commands instead of pasted as prompt text. All are single-word, exact-match (case-insensitive, trailing punctuation ignored) — `"please summarize verbatim"` pastes normally as a prompt.

| Say | Effect |
|---|---|
| `verbatim` | One-shot: the very next response is spoken in full, skipping the default Haiku summary. After that response, summary mode resumes automatically. |

### Menu-bar icons (visual state)

- 🎙️ idle
- 🔴 recording
- ⏳ transcribing
- 🔊 playing TTS
- ⚠️ error

### Audio ticks (ambient state)

Every tick is a short macOS system sound. Meant to be scannable by ear without looking at the screen.

| Sound | Fires on |
|---|---|
| **Tink** | PTT press — recording started |
| **Pop** | Transcript pasted successfully — you can release your attention |
| **Funk** | Busy or error — the daemon couldn't complete what you asked (mic denied, PortAudio wedged, etc.) |
| **Ping** | Claude Code received your prompt (`UserPromptSubmit` hook) |
| **Purr** | Claude is invoking a tool (`PreToolUse` hook) — heartbeat during work |
| **Glass** | Voice command acknowledged — currently only fires for `"verbatim"` |

Ticks respect the `feedback.sounds: true` config; set it to `false` to mute all of them at once. Spoken TTS content is controlled separately via `tts.enabled`.

## CLI

```bash
claude-voice start          # run the daemon (blocking)
claude-voice stop           # stop the daemon
claude-voice restart        # stop and start again in the background (returns immediately;
                            # useful after config changes or if PortAudio state degrades)
claude-voice interrupt      # force-stop any in-flight TTS. Fallback if a wedged say/afplay
                            # is blocking future PTT and the 60s auto-timeout hasn't fired yet.
claude-voice status         # print daemon state
claude-voice replay         # re-speak the last response
claude-voice test-mic       # record 3s, print the transcript
claude-voice test-tts "hi"  # speak a phrase via the configured provider
```

## Smoke Test

Run these in order after install:

```bash
# 1. Verify TTS works
claude-voice test-tts "hello from claude voice"

# 2. Verify STT works (will prompt for mic permission on first run)
claude-voice test-mic          # first ever run downloads the Whisper model (~500 MB, one-time).
                               # Subsequent runs — and daemon startup — read the cached weights in ~2 s.

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
- Crash logs at `~/Library/Logs/DiagnosticReports/python3.*-*.ips`

**TTS never fires when Claude finishes a response**
- Check `~/.config/claude-voice/hook.log`. If it says `daemon offline`, start the daemon.
- If the log is empty, either:
  - The `Stop` hook isn't registered — re-run `./install.sh`.
  - The hook binary isn't on Claude Code's exec PATH. Claude Code invokes hooks in a non-interactive subshell that does **not** source `~/.zshrc`, so `claude-voice-hook` sitting in `~/.local/bin`, `/opt/anaconda3/bin`, or a venv is not found. The installer resolves this via `shutil.which()` and writes the **absolute** path — verify with:
    ```bash
    grep claude-voice-hook ~/.claude/settings.json
    ```
    You should see a full path like `/opt/anaconda3/bin/claude-voice-hook`, not a bare command. If it's bare, re-run `./install.sh` from a shell where `which claude-voice-hook` resolves.

**ElevenLabs returns 404 "voice_not_found"**
- The `voice_id` must be a real ElevenLabs ID (opaque alphanumeric string like `21m00Tcm4TlvDq8ikWAM`), not a voice name.

**ElevenLabs returns 401 "paid_plan_required"**
- Free ElevenLabs plan can't use library voices via API. Either upgrade, use a voice you cloned/generated yourself, or switch `tts.provider` to `"say"`.

**Whisper transcription mangles technical terms**
- Expected on the local model. Options:
  - Bump `stt.whisper_local.model` from `small` to `medium` (better accuracy, more RAM).
  - Switch to Deepgram: `stt.provider: "deepgram"` + set `DEEPGRAM_API_KEY` in `.env`.

**TTS is stuck / playing forever / `claude-voice status` shows `"playing": true` for a long time**
- **Fastest fix:** `claude-voice interrupt` — force-terminates the current TTS subprocess.
- **Automatic:** any TTS running longer than `tts.max_duration` (default 60 s) gets auto-killed by a watchdog timer, so wedges resolve themselves within a minute even if you do nothing.
- **Also automatic:** the next PTT press force-kills any in-flight TTS before starting to record (`interrupt()` escalates from SIGTERM to SIGKILL if the subprocess doesn't die within 500 ms).
- If a wedged `say` still shows up in `ps aux | grep say` after all three, `claude-voice restart` bounces the whole daemon.

**PTT records but the ⚠️ error icon fires (`sounddevice.PortAudioError: [PaErrorCode -9986]`)**
- macOS `paInternalError` — CoreAudio's device topology drifted (headphones plugged in, video-call app grabbed exclusive input, Continuity Camera came in and out of range). The recorder auto-heals: it calls `sd._terminate() + sd._initialize()` to reset PortAudio's process-scoped state and retries once. You usually don't see this at all.
- If the retry also fails, the icon goes ⚠️ and the Funk tick plays. `claude-voice restart` reinitializes cleanly.
- If it keeps happening after restarts, verify Microphone permission is still granted (System Settings → Privacy & Security → Microphone) to the same Python interpreter you gave Accessibility to.

## Uninstall

The plugin installs three things — one Python package, one config directory, and one hook entry in Claude Code's settings. Remove them individually:

```bash
# 1. Uninstall the Python package
pip uninstall claude-voice

# 2. Remove the config directory (⚠️ wipes your config.yaml, API keys, and hook.log)
rm -rf ~/.config/claude-voice

# 3. Remove the three Stop/PreToolUse/UserPromptSubmit hooks from ~/.claude/settings.json
#    (edit by hand — the installer doesn't ship a merge-remove helper)
```

Uninstall does not remove the Whisper model weights cached under `~/.cache/huggingface/`. Delete that folder manually if you want the ~500 MB back.

## Architecture

Two independent processes:

1. **Daemon** (menu-bar app) — global PTT hotkey → `sounddevice` capture → Whisper/Deepgram → clipboard paste. Owns TTS playback so the next PTT press can interrupt it. Whisper is preloaded at startup so PTT never eats a cold-load penalty.
2. **`claude-voice-hook`** (invoked by Claude Code) — registered under three Claude Code events:
   - **`UserPromptSubmit`** — plays a Ping tick so you audibly know Claude received your prompt.
   - **`PreToolUse`** — plays a Purr tick and, if Claude wrote any interim narration for the current turn, sends it to the daemon for TTS. Uses a turn-scoped transcript reader (`read_new_assistant_since_last_user`) so stale prior-turn text is never re-spoken.
   - **`Stop`** — reads the last assistant message from the transcript, cleans it (strips code blocks, file paths, markdown), optionally summarizes via Claude Haiku, sends it to the daemon over the socket.

Communication over a Unix domain socket at `~/.config/claude-voice/daemon.sock`, line-delimited JSON.

Design details:
- Original spec: `docs/superpowers/specs/2026-07-30-voice-plugin-design.md`
- Hardening retrospective: `docs/superpowers/specs/2026-08-05-voice-plugin-hardening.md`
