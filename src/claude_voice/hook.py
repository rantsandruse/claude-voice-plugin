from __future__ import annotations
from pathlib import Path
import json
import sys
from datetime import datetime

from .config import CONFIG_DIR, load_config, load_dotenv_if_present, secrets as read_secrets
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

    load_dotenv_if_present()
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
