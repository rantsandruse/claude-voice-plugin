from __future__ import annotations
from pathlib import Path
import json
import subprocess
import sys
from datetime import datetime, timezone

from .config import CONFIG_DIR, VERBATIM_FLAG_PATH, load_config, load_dotenv_if_present, secrets as read_secrets
import hashlib
from .transcript_reader import AssistantMessage, read_new_assistant_since_last_user
from .text_cleaner import clean_for_tts
from .ipc import send_message

HOOK_LOG_PATH = CONFIG_DIR / "hook.log"

# Audio ticks played on non-Stop events so you can hear that Claude Code is
# processing without looking at the screen.
# - Ping (bright, "acknowledged"): fires when Claude Code receives your prompt
# - Purr (soft, "still working"): fires on each tool invocation
TICK_USERPROMPTSUBMIT = "Ping"
TICK_PRETOOLUSE = "Purr"


def _play_tick(sound_name: str) -> None:
    """Fire-and-forget system sound. Best-effort — failure is silent because
    the tick is UX polish, not a functional requirement."""
    try:
        subprocess.Popen(
            ["afplay", f"/System/Library/Sounds/{sound_name}.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _log(msg: str) -> None:
    try:
        HOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HOOK_LOG_PATH, "a") as fp:
            fp.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
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
    # Wall-of-text hard cap — nothing this long should ever be spoken
    # verbatim; forced summarize regardless of everything else.
    if len(text) > 5000:
        return True
    # Floor: short responses read faster verbatim than they take to
    # summarize. Skips Haiku round-trip and paraphrase mismatch — you
    # hear the exact words the assistant wrote.
    if len(text) < config.tts.min_summarize_chars:
        return False
    if config.tts.mode == "summary":
        return True
    if len(text) > config.tts.summary_threshold:
        return True
    return False


def _consume_verbatim_flag() -> bool:
    """One-shot: if the flag file exists, delete it and return True. Used to
    override summarize-by-default for the very next response."""
    if VERBATIM_FLAG_PATH.exists():
        try:
            VERBATIM_FLAG_PATH.unlink()
        except OSError:
            pass  # even a failed unlink shouldn't stop the verbatim behavior
        return True
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0

    event = payload.get("hook_event_name", "")
    load_dotenv_if_present()
    config = load_config()

    # A′: Claude Code just received a prompt and is starting a turn. The last
    # assistant message hasn't changed yet, so there's nothing to speak — just
    # confirm audibly that the submit landed and Claude is thinking.
    if event == "UserPromptSubmit":
        if config.feedback.sounds:
            _play_tick(TICK_USERPROMPTSUBMIT)
        return 0

    # B: A tool is about to run. Tick as a heartbeat, then fall through to
    # the normal TTS path — the daemon's response_id dedup means we only
    # speak new text blocks, never repeat prior ones.
    if event == "PreToolUse" and config.feedback.sounds:
        _play_tick(TICK_PRETOOLUSE)

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0

    if event == "PreToolUse":
        # Mid-turn: payload doesn't carry assistant text. Walk backwards
        # from the tail, stopping at the last real user prompt — returns
        # None if no new text exists yet, avoiding a re-speak of the prior
        # turn while Claude is still thinking about the current one.
        msg = read_new_assistant_since_last_user(Path(transcript_path))
    else:
        # Stop: the payload carries the exact assistant text that triggered
        # this hook invocation as `last_assistant_message`. Using it directly
        # eliminates the transcript-scan races that a file-based reader is
        # subject to (flush timing gap between thinking/text JSONL entries;
        # a next-turn PTT landing in the file before we read). Claude Code
        # doesn't include the API message id here, so we synthesize one
        # from a text hash to keep the daemon's (response_id, text) dedup
        # working.
        last_asst = payload.get("last_assistant_message", "") or ""
        if not last_asst.strip():
            return 0
        text_hash = hashlib.sha1(last_asst.encode("utf-8", errors="replace")).hexdigest()[:16]
        msg = AssistantMessage(id=f"stop_{text_hash}", content=last_asst)
    if msg is None:
        return 0

    cleaned = clean_for_tts(msg.content)
    if not cleaned:
        return 0

    # Snapshot the daemon's turn generation BEFORE doing anything blocking
    # (Haiku summarize, secrets read). We stamp the speak with this number
    # so the daemon can drop us if the user has moved to a new turn during
    # our processing — see DaemonCore.handle_speak. Failing to query
    # (daemon offline) just means we omit the stamp and the daemon plays
    # unconditionally, matching the old behavior.
    gen_reply = send_message({"op": "generation"})
    generation = gen_reply.get("generation") if isinstance(gen_reply, dict) else None

    secrets = read_secrets()

    text = cleaned
    # One-shot override wins over config: user asked for verbatim, they get
    # verbatim regardless of mode or thresholds.
    if _consume_verbatim_flag():
        pass
    elif _should_summarize(cleaned, config):
        api_key = secrets.get("ANTHROPIC_API_KEY")
        if api_key:
            text = summarize(cleaned, api_key)

    speak_msg = {
        "op": "speak",
        "text": text,
        "response_id": msg.id,
    }
    if isinstance(generation, int):
        speak_msg["generation"] = generation
    reply = send_message(speak_msg)
    if reply is None:
        _log(f"daemon offline; skipped speaking msg_id={msg.id}")
    return 0
