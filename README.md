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

The installer creates `~/.config/claude-voice/` and registers three hooks in `~/.claude/settings.json` (`Stop`, `PreToolUse`, `UserPromptSubmit`). Then, in any focused text field:

1. Hold **Right Option**, speak, release. The transcript pastes and auto-submits.
2. Wait for Claude's answer — you'll hear a Ping when it starts thinking, a Purr for each tool it runs, and a spoken summary when it's done.

**One-time permissions.** macOS will prompt for **Microphone** access on your first PTT press. Grant **Accessibility** to Terminal (or iTerm) *and* your Python interpreter before the first PTT — full details in [Grant macOS Permissions](#grant-macos-permissions-required) below.

Everything after this point is reference material — skim as needed.

## Requirements

- macOS 14+ (Sonoma or later)
- Python 3.11+
- ~500 MB free disk space (for the Whisper `small` model, downloaded on first use)
- **`ANTHROPIC_API_KEY`** — required if you use summary mode (the default). Every response goes through Claude Haiku before being spoken. Skip only if you switch to `tts.mode: "prose"`.
- Optional: API keys for [Deepgram](https://deepgram.com) (STT) and/or [ElevenLabs](https://elevenlabs.io) (TTS) if you want cloud quality

## Grant macOS Permissions (required)

Before your first PTT press, grant two permissions in **System Settings → Privacy & Security**:

- **Accessibility** — add your terminal (`Terminal.app` or `iTerm.app`) *and* the Python interpreter you installed the package into (find with `which python3`). Required so the daemon can paste with ⌘V.
- **Microphone** — macOS prompts automatically on first PTT. Grant to the same terminal and Python.

If PTT does nothing or you see "osascript is not allowed to send keystrokes," Accessibility isn't granted — see [Troubleshooting](#troubleshooting).

## Configure

Config lives at `~/.config/claude-voice/config.yaml` — see [`config.yaml.example`](./config.yaml.example) for the full schema with inline comments.

Keys you'll actually touch:

- `hotkey.ptt` — default `alt_r` (Right Option). Also: `alt_l`, `cmd_r`, `f1..f12`.
- `stt.provider` — `whisper_local` (default, offline) or `deepgram` (cloud).
- `tts.provider` — `say` (default, offline, macOS built-in) or `elevenlabs` (cloud).
- `tts.mode` — `summary` (default, Haiku condenses) or `prose` (verbatim).

Put API keys in `~/.config/claude-voice/.env`:
```
DEEPGRAM_API_KEY=...     # optional: only needed if you set stt.provider: "deepgram"
ELEVENLABS_API_KEY=...   # optional: only needed if you set tts.provider: "elevenlabs"
ANTHROPIC_API_KEY=...    # needed for summary mode (default). Skip only if you set tts.mode: "prose".
```

## Usage

Push-to-talk basics are in the [Quick Start](#quick-start). What follows are the voice-controlled and ambient behaviors that build on it.

**Interrupt playing TTS:** press the PTT hotkey while Claude is speaking. Playback stops and recording starts immediately. (For a force-kill from the terminal when PTT itself isn't reaching the daemon, see `claude-voice interrupt` in the [CLI](#cli) section.)

### Voice commands

Some utterances are intercepted as commands instead of pasted as prompt text. All are single-word, exact-match (case-insensitive, trailing punctuation ignored) — `"please summarize verbatim"` pastes normally as a prompt.

| Say | Effect |
|---|---|
| `verbatim` | One-shot: the very next response is spoken in full, skipping the default Haiku summary. After that response, summary mode resumes automatically. |

### Feedback signals

**Menu-bar icon** — 🎙️ idle · 🔴 recording · ⏳ transcribing · 🔊 playing TTS · ⚠️ error.

**Audio ticks** — short macOS system sounds signal state changes, scannable by ear without looking.

<details>
<summary>Full sound reference</summary>

| Sound | Fires on |
|---|---|
| **Tink** | PTT press — recording started |
| **Pop** | Transcript pasted successfully — you can release your attention |
| **Funk** | Busy or error — the daemon couldn't complete what you asked (mic denied, PortAudio wedged, etc.) |
| **Ping** | Claude Code received your prompt (`UserPromptSubmit` hook) |
| **Purr** | Claude is invoking a tool (`PreToolUse` hook) — heartbeat during work |
| **Glass** | Voice command acknowledged — currently only fires for `"verbatim"` |

</details>

Ticks respect the `feedback.sounds: true` config; set to `false` to mute all at once. Spoken TTS content is controlled separately via `tts.enabled`.

## CLI

```bash
claude-voice start          # run the daemon (blocking)
claude-voice stop           # stop the daemon
claude-voice restart        # stop and start again in the background
claude-voice interrupt      # force-stop any in-flight TTS
claude-voice status         # print daemon state
claude-voice replay         # re-speak the last response
claude-voice test-mic       # record 3s, print the transcript
claude-voice test-tts "hi"  # speak a phrase via the configured provider
```

## Voices (`say` provider)

<details>
<summary>Install Premium voices, list available voices</summary>

macOS ships tiered TTS voices — all free, all offline. **Ava (Premium)** is Siri-quality; install via **System Settings → Accessibility → Spoken Content → System Voice → Manage Voices…** and download any voice marked *(Premium)* under your locale — ~400 MB each, one-time.

Preview from terminal (once installed):
```bash
say -v "Ava (Premium)" "This is a sample of the Ava premium voice."
```

List every voice on your system:
```bash
say -v '?' | grep en_US
```

</details>

## Troubleshooting

<details>
<summary>Diagnostic recipe if Quick Start didn't work + common issues</summary>

**Diagnostic recipe.** If Quick Start didn't work end-to-end, isolate which piece is broken:

```bash
claude-voice test-tts "hello from claude voice"   # verify TTS
claude-voice test-mic                              # verify STT
                                                   # first ever run downloads Whisper ~500 MB
                                                   # subsequent runs and daemon start read cached weights in ~2s
claude-voice start                                 # daemon should stay up and show 🎙️
```

**No menu bar icon appears after `claude-voice start`**
- Check the daemon is actually running: `claude-voice status` in another terminal. If it returns JSON, the daemon is alive but the icon didn't register — try `claude-voice stop && claude-voice start`.
- Multiple monitors: the icon shows on the active display's menu bar only.
- Menu bar full / notch: mouse to top-right, or hide other icons.

**PTT does nothing / "osascript is not allowed to send keystrokes"**
- Accessibility permission not granted. Follow the Permissions section above.
- After granting, fully quit Terminal (⌘Q) and restart the daemon.

**Segmentation fault on first PTT press (macOS 14+)**
- Known `sounddevice` / `portaudio` interaction. Should be fixed by the built-in Recorder patch. If it persists, run the daemon in-line to get a Python traceback: `python -c "from claude_voice.daemon import run_daemon; run_daemon()"`
- Crash logs at `~/Library/Logs/DiagnosticReports/python3.*-*.ips`

**TTS never fires when Claude finishes a response**
- Check `~/.config/claude-voice/hook.log`. If it says `daemon offline`, start the daemon.
- If the log is empty, either the `Stop` hook isn't registered (re-run `./install.sh`), or the hook binary isn't on Claude Code's exec PATH. Claude Code invokes hooks in a non-interactive subshell that does **not** source `~/.zshrc`, so `claude-voice-hook` sitting in `~/.local/bin`, `/opt/anaconda3/bin`, or a venv is not found. The installer resolves this via `shutil.which()` and writes the **absolute** path — verify with `grep claude-voice-hook ~/.claude/settings.json`. You should see a full path like `/opt/anaconda3/bin/claude-voice-hook`, not a bare command. If it's bare, re-run `./install.sh` from a shell where `which claude-voice-hook` resolves.

**Whisper transcription mangles technical terms** — expected on the local model. Bump `stt.whisper_local.model` from `small` to `medium` (better accuracy, more RAM), or switch to Deepgram (`stt.provider: "deepgram"` + set `DEEPGRAM_API_KEY`).

**TTS is stuck / playing forever / `claude-voice status` shows `"playing": true` for a long time**
- **Fastest fix:** `claude-voice interrupt` — force-terminates the current TTS subprocess.
- **Automatic:** any TTS running longer than `tts.max_duration` (default 60 s) gets auto-killed by a watchdog timer, so wedges resolve themselves within a minute even if you do nothing.
- **Also automatic:** the next PTT press force-kills any in-flight TTS before starting to record.
- If a wedged `say` still shows up in `ps aux | grep say` after all three, `claude-voice restart` bounces the whole daemon.

**PTT records but the ⚠️ error icon fires (`sounddevice.PortAudioError: [PaErrorCode -9986]`)**
- macOS `paInternalError` — CoreAudio's device topology drifted (headphones plugged in, video-call app grabbed exclusive input, Continuity Camera came in and out of range). The recorder auto-heals: it resets PortAudio's process-scoped state and retries once. You usually don't see this at all.
- If the retry also fails, the icon goes ⚠️ and the Funk tick plays. `claude-voice restart` reinitializes cleanly.
- If it keeps happening after restarts, verify Microphone permission is still granted to the same Python interpreter you gave Accessibility to.

</details>

## Uninstall

<details>
<summary>Remove the Python package, config dir, and hook entries</summary>

```bash
# 1. Uninstall the Python package
pip uninstall claude-voice

# 2. Remove the config directory (⚠️ wipes your config.yaml, API keys, and hook.log)
rm -rf ~/.config/claude-voice

# 3. Remove the three Stop/PreToolUse/UserPromptSubmit hooks from ~/.claude/settings.json
#    (edit by hand — the installer doesn't ship a merge-remove helper)
```

Uninstall does not remove the Whisper model weights cached under `~/.cache/huggingface/`. Delete that folder manually if you want the ~500 MB back.

</details>

## Architecture

Two processes talking over a Unix domain socket at `~/.config/claude-voice/daemon.sock`. Full design details:

- Original spec: [`docs/design.md`](./docs/design.md)
- Hardening retrospective: [`docs/hardening.md`](./docs/hardening.md)
</content>
</invoke>