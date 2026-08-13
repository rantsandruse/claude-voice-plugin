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


def _is_real_user_prompt(entry: dict) -> bool:
    """Distinguish a real user prompt from a tool_result injection. Claude Code
    records both with type=="user", but tool_results have only tool_result
    blocks in the content list. Real prompts have a string or contain text
    blocks."""
    msg = entry.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            for b in content
        )
    return False


def read_new_assistant_since_last_user(transcript_path: Path) -> AssistantMessage | None:
    """Return the last assistant text block only if it was emitted after the
    most recent real user prompt. Otherwise None — the assistant hasn't said
    anything new in this turn yet.

    Used by the PreToolUse hook so restart-cleared dedup state doesn't cause
    stale prior-turn text to be re-spoken while Claude is still thinking
    about the current turn."""
    if not transcript_path.exists():
        return None
    entries: list[dict] = []
    with open(transcript_path) as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for entry in reversed(entries):
        etype = entry.get("type")
        if etype == "user" and _is_real_user_prompt(entry):
            # Walked back to the current turn's boundary without finding new
            # assistant text — nothing to speak yet.
            return None
        if etype == "assistant":
            msg = entry.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            msg_id = msg.get("id") or entry.get("uuid") or ""
            content = _extract_content(msg.get("content"))
            if content:
                return AssistantMessage(id=msg_id, content=content)
    return None
