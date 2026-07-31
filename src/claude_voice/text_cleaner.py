from __future__ import annotations
import re

# Whisper is known to hallucinate these phrases on silence/noise.
WHISPER_HALLUCINATION_PATTERNS: list[str] = [
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "see you next time",
    "bye bye",
    ".",  # single period from empty audio
]

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_TOOL_USE = re.compile(r"<tool_use>.*?</tool_use>", re.DOTALL | re.IGNORECASE)
_FILE_PATH = re.compile(r"(?:[\w\-.]+/)+[\w\-.]+\.[a-zA-Z0-9]{1,6}")
_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_BOLD_ITALIC = re.compile(r"(\*\*|__|\*|_)")
_LIST_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MULTI_NEWLINE = re.compile(r"\n{2,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_for_tts(text: str) -> str:
    if not text:
        return ""
    text = _TOOL_USE.sub("", text)
    text = _FENCED_CODE.sub("", text)
    text = _INLINE_CODE.sub(lambda m: m.group(0).strip("`"), text)
    text = _FILE_PATH.sub("a file", text)
    text = _HEADING.sub("", text)
    text = _BOLD_ITALIC.sub("", text)
    text = _LIST_BULLET.sub("", text)
    text = _NUMBERED_LIST.sub("", text)
    text = _MULTI_NEWLINE.sub("\n", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()
