# Voice Plugin — Hardening & Latency Retrospective

**Date:** 2026-08-05
**Status:** Landed, uncommitted
**Companion doc:** `2026-07-30-voice-plugin-design.md`

## Context

The original design landed a working plugin on 2026-07-30. Between then and 2026-08-04, real use exposed a class of issue the design phase couldn't have caught: **runtime rules**. On 2026-08-04 the daemon began crashing after a few PTT presses. It left a stale Unix socket behind, which silently blocked every subsequent `claude-voice start`. The Stop hook logged 13+ hours of `daemon offline; skipped speaking` before the failure was investigated.

This retrospective documents the decisions made in one 2026-08-05 debugging + hardening session, ordered by **severity** — the criterion for each entry is *"if this bug hit you, how bad was your day?"*.

Every **Critical** fix here is a runtime discovery, not a design gap. You couldn't have caught them on a whiteboard.

---

## Critical — plugin doesn't work; user is blocked

Each item, on its own, made the tool functionally unusable.

### C1 — AppKit-thread crash: `_on_state_change` from workers

**Symptom.** Daemon segfaults after a few PTT presses. macOS diagnostic report at `~/Library/Logs/DiagnosticReports/python3.12-YYYY-MM-DD-HHMMSS.ips` shows `EXC_BAD_ACCESS (SIGSEGV)` on a background thread with this frame stack:

```
objc_release
CA::release_objects(X::List<void const*>*)
CA::Transaction::commit()
CA::Transaction::release_thread(void*)
_pthread_tsd_cleanup
_pthread_exit
```

**Root cause.** Core Animation and `NSStatusItem` are strictly main-thread. `VoiceDaemon._on_state_change` did `self.title = icon` — a rumps property setter that reaches into AppKit. It was invoked from three different background threads:

1. The transcribe worker spawned by `_default_dispatch` on PTT release
2. The IPC handler thread inside `IPCServer._handle_conn` (via `handle_speak`, `handle_replay`)
3. The `pynput.keyboard.Listener` thread (via `handle_hotkey`)

Each background thread that touched `NSStatusItem` had ObjC/Cocoa lazily attach a per-thread Core Animation transaction. When that thread later exited, `_pthread_tsd_cleanup` ran the transaction destructor — and the ObjC objects it tried to release were already invalid, so `objc_release` faulted. The fault was probabilistic: it depended on GC timing and when the CA commit ran, which is why the daemon survived a few presses before dying.

The `resource_tracker: leaked semaphore` warning at process exit was a downstream symptom, not a separate bug: `faster_whisper` (via `ctranslate2`) holds POSIX semaphores for its OpenMP threadpool; when the process aborts on SIGSEGV mid-transcription, those semaphores never get released.

**Decision.** Marshal every AppKit-touching state change back onto the main run loop via `PyObjCTools.AppHelper.callAfter`.

```python
def _on_state_change(self, state: str) -> None:
    icon = _STATE_ICONS.get(state, "🎙️")
    callAfter(lambda: setattr(self, "title", icon))
```

Placing the marshal inside `_on_state_change` itself means callers stay simple — every entry point (worker, IPC, hotkey) is safe without individual thought.

**Alternatives considered.**
- `NSObject.performSelectorOnMainThread_withObject_waitUntilDone_(False)` — more machinery for the same effect, less idiomatic in a PyObjC/rumps app.
- Route all state changes through a queue read by a `rumps.Timer` — adds latency (polling interval) for no benefit.
- Add locks around AppKit calls — doesn't help. The bug is thread-of-invocation, not concurrent access.

**Not yet addressed.** `_quit_handler` calls `rumps.quit_application()` from the IPC thread — same category of bug on paper. Its blast radius is tiny (the process exits immediately after), so it was documented but not fixed. Trivial to add `callAfter(rumps.quit_application)` when convenient.

**Code:** `src/claude_voice/daemon.py:229-236` (`_on_state_change` body); `src/claude_voice/daemon.py:9` (`callAfter` import).

### C2 — Socket lifecycle: stale sockets block restart, signal handlers race AppKit

**Symptom.** After any daemon crash (including the C1 segfault), every subsequent `claude-voice start` silently failed to serve requests. `claude-voice status` reported the daemon healthy; the Stop hook wrote `daemon offline` to `hook.log` anyway. Ctrl+C in the foreground terminal produced additional crashes.

**Root cause.** Two sides of the same coin — the socket's *lifecycle* was under-specified.

*Startup:* `IPCServer.start()` did unlink the socket path before binding, but only inside the server thread after `VoiceDaemon.__init__` had already run and started other machinery. The window between "old daemon crashed" and "new daemon start succeeds" was fragile and depended on ordering.

*Shutdown:* The original code registered SIGINT/SIGTERM handlers that called `rumps.quit_application()` from the signal thread. AppKit's main run loop was mid-frame; the quit call raced with it. On Ctrl+C the process either segfaulted or exited half-way through cleanup, leaving `~/.config/claude-voice/daemon.sock` behind. Next `claude-voice start` would then find the file, believe another daemon owned it, and fail to bind.

**Decision.** Rewrite both endpoints of the socket's lifecycle:

- **Startup unlink** immediately after `load_config()` and before `VoiceDaemon.__init__`, so any stale socket from a crashed predecessor is cleaned before any new machinery starts. Failures are swallowed (`OSError` pass) because the socket may not exist.
- **Shutdown via `atexit`** instead of signal handlers. `atexit` fires after rumps' main loop returns naturally, so there's no race with AppKit. The tradeoff: Ctrl+C in the foreground no longer gracefully shuts down (Python raises KeyboardInterrupt but rumps swallows it). In practice the daemon is quit via the menu-bar Quit item or `claude-voice stop`, so this is acceptable.

```python
def run_daemon() -> None:
    ...
    try:
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
    except OSError:
        pass

    daemon = VoiceDaemon(config, secrets)

    import atexit
    def _cleanup():
        try: daemon._core.stop()
        except Exception: pass
    atexit.register(_cleanup)
    daemon.run()
```

**Alternatives considered.**
- Keep the signal handlers, wrap `rumps.quit_application()` in `callAfter`. Would work, but atexit is simpler and handles more exit paths (menu-bar Quit, `claude-voice stop` via IPC, normal process termination).
- Abstract-namespace socket (Linux-style, no filesystem entry) — not supported on macOS; also would break the CLI's connect logic.

**Code:** `src/claude_voice/daemon.py:255-260` (startup unlink); `src/claude_voice/daemon.py:279-290` (atexit registration).

### C3 — Hook PATH silent-fail: bare command name unresolvable in Claude Code's exec env

**Symptom.** `settings.json` had a Stop hook registered as `"command": "claude-voice-hook"`. Every Claude Code Stop event fired an `afplay` bell (the other Stop hook) but no TTS ever spoke. `hook.log` had no entries — because the hook binary never ran.

**Root cause.** Claude Code invokes hook commands in a non-interactive subshell. Non-interactive shells don't source `~/.zshrc`. On this machine, `/opt/anaconda3/bin/` (where `claude-voice-hook` lives) is added to PATH *only* by `.zshrc` — not `.zprofile`, which is what non-interactive login shells actually source. Result: `claude-voice-hook` resolves as "command not found", Claude Code discards the failure, no user-visible signal.

Confirmed via: `env -i HOME=$HOME zsh -c 'command -v claude-voice-hook'` → `NOT_FOUND`. The `afplay` bell worked because `/usr/bin` is always on PATH.

**Decision.** Have the installer resolve `claude-voice-hook` to an absolute path via `shutil.which()` at merge time, and write that absolute string into `settings.json`. The `merge_stop_hook()` helper keeps its default arg (`"claude-voice-hook"`) unchanged for testability; the `_cli` entrypoint resolves and passes through.

```python
resolved = shutil.which("claude-voice-hook") or "claude-voice-hook"
merged = merge_stop_hook(data, command=resolved)
```

**Alternatives considered.**
- Ask users to add `/opt/anaconda3/bin` (or wherever) to `.zprofile` — fragile, environment-specific, doesn't scale.
- Wrap the hook in a shell script that sets PATH itself — extra indirection, extra file to install.
- Ship a launcher `.sh` in the repo that Claude Code invokes — same as above with more moving parts.

`shutil.which()` runs at install time on the target machine, so it captures whatever Python/venv/conda the user actually installed the package into. No config, no environment assumptions.

**Migration.** Users with pre-fix installs need to either re-run `python -m claude_voice._install merge-settings` (dedup by exact string means the old bare entry stays, and a new absolute entry gets added — currently produces a duplicate) or manually edit `settings.json`. A future improvement to the installer would migrate bare entries in place.

**Code:** `src/claude_voice/_install.py:47-49`.

---

## Major — visible degradation; user notices

Plugin works but feels bad enough to be a real UX problem.

### M1 — Cold-load first-PTT latency

**Symptom.** First PTT press after `claude-voice start` takes 3–10 seconds longer than subsequent ones.

**Root cause.** `WhisperLocalProvider._model_get()` was lazy — the first `.transcribe()` call triggered the model download (if not cached) or load (from disk, ~500 MB for the `small` model) in-band. Every press after that used the cached instance, so only the first felt slow.

**Decision.** Preload weights at daemon start. Added a `warmup()` method on `WhisperLocalProvider` that calls `_model_get()`; called from `VoiceDaemon.__init__` right after `_make_stt(...)`. Uses `getattr(stt, "warmup", None)` so cloud providers (Deepgram) can no-op.

```python
warmup = getattr(stt, "warmup", None)
if callable(warmup):
    print("[daemon] preloading STT model…", file=sys.stderr)
    try: warmup()
    except Exception as e:
        print(f"[daemon] STT warmup failed: {e}", file=sys.stderr)
```

**Tradeoff.** `claude-voice start` now blocks ~2s longer on the machine measured. In exchange, every PTT press feels identical from the very first one. Failure is non-fatal — logs and falls through to lazy-load-on-first-press.

**Code:** `src/claude_voice/stt/whisper_local.py:36-38` (`warmup`); `src/claude_voice/daemon.py:186-198` (call from `VoiceDaemon.__init__`).

### M2 — Steady-state STT inefficiency

**Symptom.** Every PTT press takes 2–3× longer to transcribe than necessary.

**Root cause.** The transcribe call passed no tuning arguments:

```python
segments, _ = self._model_get().transcribe(str(wav_path), language=self._config.language)
```

Three defaults were expensive and wrong for the use case:

- `beam_size=5` — beam search is 2–3× slower than greedy. On short PTT utterances the quality difference is negligible.
- `vad_filter=False` — silero-VAD isn't run, so leading/trailing silence in the recording (unavoidable with PTT hold-release) gets fed through the encoder for no benefit.
- `condition_on_previous_text=True` — Whisper conditions each generation on the previous output. On PTT, every press is a standalone utterance, so previous context is either irrelevant or wrong.

**Decision.** Bake all three into a module-level tuning dict and apply to every transcribe call:

```python
_TRANSCRIBE_KWARGS = dict(
    beam_size=1,
    vad_filter=True,
    condition_on_previous_text=False,
)
```

**Tradeoff.** `beam_size=1` (greedy) can be marginally lower quality on ambiguous phonemes. Deferred fallback: if accuracy drops on technical terms, `beam_size` gets bumped to 2 (still 30% faster than default). Deeper fallback: downshift/upshift the model (`small` → `medium` for quality, or `tiny`/`base` for even more speed).

**Code:** `src/claude_voice/stt/whisper_local.py:11-19` (tuning constants), applied at `:44` and `:56`.

### M3 — WAV round-trip on hot path, disk holds raw voice for up to 3 days

**Symptom.** Every PTT press wrote a WAV file to `/tmp/claude-voice/<timestamp>.wav`; the STT provider then re-read that file. ~50–100 ms wasted per press. Files accumulated in `/tmp` until macOS's `/etc/periodic/daily/110.clean-tmps` reaped them 3 days later.

**Root cause.** The original design chose file-based interfaces between components for simplicity — `Recorder.stop()` returned a `Path`, and both STT providers took a `Path`. Correct for the design phase; wrong once we started measuring.

**Decision.** Refactor the hot path to pass audio in memory as a numpy array.

- `Recorder.stop()` now returns `(np.ndarray, int) | None` — the float32 audio in [-1, 1] and its sample rate. No disk write.
- Both STT providers gained `transcribe_audio(audio: np.ndarray, sample_rate: int) -> str`:
  - `WhisperLocalProvider.transcribe_audio` passes the array directly to `WhisperModel.transcribe`, which accepts numpy input natively.
  - `DeepgramProvider.transcribe_audio` encodes the audio to WAV bytes in-memory via `wave` + `io.BytesIO` and POSTs them; the wire format didn't change, only the source of the bytes.
- `run_transcribe_job` was updated to unpack the tuple and call `transcribe_audio`. The obsolete `wav.unlink()` cleanup in the finally block was removed.

Legacy path retained: `Recorder.stop_to_wav()` and `WhisperLocalProvider.transcribe(wav_path)` still exist for the `claude-voice test-mic` CLI command, which prints a wav path to the user. Not on the PTT hot path.

**Tradeoff.** More surface area on both providers (an `_audio` method alongside the file method). Justified because the wire representation of Deepgram (WAV bytes) is genuinely different from what Whisper wants (float32 numpy), so a shared method wouldn't share much implementation.

**Privacy bonus.** No unencrypted voice audio ever lands on disk during normal PTT operation. Previously users' raw recordings sat in `/tmp` up to 72 hours.

**Code:** `src/claude_voice/recorder.py:44-71` (new `stop`); `src/claude_voice/recorder.py:73-89` (retained `stop_to_wav`); `src/claude_voice/stt/whisper_local.py:47-58` (`transcribe_audio`); `src/claude_voice/stt/deepgram.py:19-31` (`transcribe_audio`); `src/claude_voice/daemon.py:83-115` (updated PTT flow).

---

## Minor — hygiene and defense-in-depth

Nobody would notice these missing. They're worth doing anyway because they close windows for future crashes to leave junk behind.

### m1 — Retained `stop_to_wav` as opt-in for CLI test-mic

`claude-voice test-mic` records 3 seconds and prints the transcript for smoke-testing after install. It previously needed a wav path to display. With the M3 refactor removing disk writes from `Recorder.stop`, the CLI command would have broken. Kept the file-writing path as `Recorder.stop_to_wav()`, called only from CLI. The PTT hot path never touches it.

**Code:** `src/claude_voice/recorder.py:73-89`; `src/claude_voice/cli.py:63-74`.

### m2 — Defensive startup wav purge

Pre-fix installs (and any future daemon that crashes before finalization) may leave wav files in `/tmp/claude-voice/`. Added `_purge_old_wavs(older_than_hours=24)` called from `run_daemon()`. Sweeps files older than 24 hours — tighter than macOS's 3-day `/tmp` reap window, without deleting anything a running session might legitimately be holding.

**Code:** `src/claude_voice/daemon.py:237-249`.

---

## Enhancement — new capability, not fixing a bug

### E1 — PreToolUse hook for interim narration

**Motivation.** The Stop hook only fires at end-of-turn. Interim status lines emitted before tool calls ("Let me check the docs first…") never got spoken. The user wanted to hear the plan before the tool ran.

**Investigation.** Inspecting the live session transcript revealed that Claude Code assigns each text block its own unique `msg_id`, even within a single turn:

```
msg_...Ang  blocks=['text']      "Let me check the docs conventions first..."
msg_...Ang  blocks=['tool_use']
msg_...ApJ  blocks=['tool_use']
msg_...Aq5  blocks=['text']      "I'll write it in the same style..."
```

The daemon's existing `response_id` dedup (`response_id == self._last_spoken_response_id`) already handles this correctly with **zero code changes** — each text block presents a fresh `msg_id`, so it's spoken exactly once; repeats within the same block dedupe naturally.

**Decision.** Register the same `claude-voice-hook` binary under `PreToolUse` as well, with `matcher: ""` (fires on every tool). Installer updated to write both events. Added `merge_pretooluse_hook()` and refactored the shared logic into `_merge_event_hook()`.

**Deferred controls.** Considered adding a `min_speak_chars: 40` threshold to prevent short interstitials ("OK, one more thing.") from firing TTS. Decided to ship without the threshold and see whether the chatter is actually a problem before adding UX knobs.

**Code:** `src/claude_voice/_install.py:8-35` (shared `_merge_event_hook`); `src/claude_voice/_install.py:37-48` (both wrappers); `tests/test_install.py:9-32` (new tests).

---

## What we consciously did *not* do

- **`_quit_handler` → `callAfter`.** Same class of bug as C1 (AppKit call from IPC thread), but its blast radius is one final teardown at process exit. Deferred as follow-up.
- **`min_speak_chars` threshold on PreToolUse.** Wait and see if chatter is real before shipping controls.
- **Model downshift (`small` → `base`/`tiny`).** M1 + M2 may already be enough; revisit if user still finds latency uncomfortable.
- **Cloud STT (Deepgram) as new default.** Preserves offline-first ideology from the original design. Deepgram remains a configurable option.
- **Bare-command migration in installer.** If a user's `settings.json` still has bare `claude-voice-hook`, re-running the installer *appends* an absolute-path entry instead of upgrading in place, producing a duplicate. Would be a nice improvement to `_merge_event_hook`.
- **Wire `logging.level` / `logging.path`.** Pre-existing TODO; unchanged this session. Modules still use ad-hoc `print(..., file=sys.stderr)`.

---

## Lessons for the original design doc

Amendments worth noting in `2026-07-30-voice-plugin-design.md` (as a "post-implementation notes" appendix rather than editing the body):

1. **AppKit thread rule is load-bearing.** The design spec's single line "main-thread event loop for the menu bar" understated the constraint. Any code path that mutates rumps state — even a one-line `self.title = "..."` — must marshal to main. Future contributors should assume every callback runs on the wrong thread until proven otherwise.

2. **Hook exec environment is not the user's shell.** The install-flow section assumed `claude-voice-hook` would be on PATH. It isn't, unless the shell that launched Claude Code exported PATH to the child process (login shell) *or* the hook command is absolute. Future hooks should register with absolute paths.

3. **Runtime primitives that leak background state need explicit cleanup.** `sounddevice` (portaudio), `ctranslate2` (OpenMP), rumps (NSStatusItem), IPC socket — all held resources that Python's default abort path couldn't reclaim cleanly. Design docs should call out per-component teardown requirements.

4. **File-based interfaces should be justified, not defaulted.** The original spec chose `Recorder → Path → STT` for simplicity, which was reasonable. But the WAV was never consumed by anything except the immediate next component, and the write was pure overhead. Rule of thumb: file interfaces should be justified by cross-process communication or debuggability, not by inertia.

5. **PreToolUse is a real product surface.** The design named `Stop` as the sole TTS trigger. In practice, users want to hear the plan before tools run. Amend the "Component 2: Stop Hook" section to name both hooks. Interim narration comes free because per-block `msg_id` gives natural dedup.
