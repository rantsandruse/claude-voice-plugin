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
