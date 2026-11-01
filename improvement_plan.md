# Claude Voice Plugin Improvement Plan

Revised 2026-10-26 after checking the ideas against the current code.

## What the code already does

Some of the original ideas are partly built, which changes their cost:

- **VAD exists.** Tap-to-talk already runs Silero VAD (`endpoint.py`) to detect end of speech. Hands-free work can reuse it instead of adding a new VAD.
- **Progress audio exists.** `PreToolUse` already plays a Purr tick per tool and speaks any new assistant text written mid-turn.
- **Summaries are weak by design.** `hook.summarize` asks Haiku for "1-2 short spoken sentences" with `max_tokens=200`. Any reply with options, steps or a question loses them. This is the cheapest big win.
- **Voice commands exist.** `verbatim` is intercepted in `daemon.run_transcribe_job`, so adding more commands is easy.

## Priorities

| # | Item | Value | Cost | Status |
|---|---|---|---|---|
| P1 | Summary rules: keep options, steps, questions, decisions | High | Small | Done |
| P1 | "more" voice command: speak the last reply in full | High | Small | Done |
| P1 | Optional `Spoken:` section written by Claude | Medium | Small | Done |
| P2 | Test Remote Control + Mac speech (no code) | Medium | 10 min | To do (you) |
| P2 | Conversation mode: double-tap, mic reopens after each spoken reply | High | Medium | Built, testing |
| P2 | Spoken progress lines ("running tests") | Medium | Small–Medium | To do |
| P3 | Timeboxed look at AgentsRoom (30 min) | Low–Medium | Small | Before conversation mode |
| P3 | Wake word | Medium | Large | Later |
| Drop | Headless streaming mode | — | Large | Dropped |
| Park | Phone web page over Tailscale | — | Large | Parked |

## P1: Better spoken summaries (done)

- **Summary rules.** The Haiku prompt now says what must survive: options, fixes, steps, questions and decisions are read as a numbered list, one sentence each. Reasoning and background get condensed. Length scales with content, not a fixed "1-2 sentences".
- **"more" command.** Say just "more" (or "tell me more") after a summary to hear the whole reply. The daemon keeps the full text of the last reply.
- **`Spoken:` section (opt-in).** If a reply ends with a `Spoken:` section, the hook speaks only that, word for word, and skips Haiku. Turn it on by adding a rule to your `CLAUDE.md` (snippet in the README). Opt-in because it adds text to every on-screen reply and depends on Claude following the rule; Haiku stays as the fallback.

## P2: Away from the computer

- Test first: run `/remote-control`, send a prompt from the phone, check the Mac still speaks. Should work since speech comes from the hook.
- Caveat: Mac speech only helps if you can hear the Mac. Truly away, the phone's dictation + Speak Screen is the zero-code option.
- The Tailscale web page is a separate app (auth, audio streaming, a second TTS path). Parked until Remote Control shows a real gap.

## P2: Conversation mode (replaces "always-on VAD" as the first step)

- After a spoken reply finishes, open the mic once, the way tap-to-talk does. Speak to reply; stay quiet for ~5 s and it closes.
- Reuses the existing `EndpointDetector` (`no_speech_timeout_s` already handles "nothing said").
- Echo goes away: the mic only opens after TTS ends. No echo cancellation needed.
- Risk to handle: the transcript pastes into whatever window has focus. Only reopen if the terminal that started the turn is still frontmost.
- Toggle from the menu bar and config, off by default.

## P2: Spoken progress lines

- Build short lines from `PreToolUse`'s `tool_name` and `tool_input` with templates, no LLM: "Reading config.py", "Running tests", "Editing hook.py".
- Rate-limit (at most one every ~5 s) and drop lines that go stale, so they don't pile up in the TTS queue (speech now queues instead of interrupting).
- Opt-in setting; the Purr tick stays the default.

## P3: Wake word (later)

- openWakeWord with a distinctive phrase. Needs an always-open mic (privacy, battery), false-trigger tuning, and the focus problem above.
- Conversation mode covers most of the hands-free need; revisit wake word only if that's not enough.

## Dropped: headless streaming

Running Claude Code in headless `stream-json` mode means giving up the interactive terminal, which breaks the plugin's core promise (works with an unmodified `claude` CLI). Progress lines + the end summary cover most of the wait-time problem.

## Off-the-shelf alternatives

- **AgentsRoom** (agentsroom.dev): hands-free mode that reopens the mic after each reply. Spend 30 minutes on it before building conversation mode: does it summarise, can you choose what's read, does it work with a plain terminal?
- **Claude Code built-in voice:** push-to-talk input only, no spoken replies.
- **Codex:** voice input, text replies; controllable from the ChatGPT phone app.
