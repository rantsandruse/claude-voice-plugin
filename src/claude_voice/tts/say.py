from __future__ import annotations
import subprocess

from ..config import SayConfig


class SayProvider:
    def __init__(self, config: SayConfig):
        self._config = config

    def speak(self, text: str) -> subprocess.Popen:
        if not text or not text.strip():
            raise ValueError("empty text")
        return subprocess.Popen(["say", "-v", self._config.voice, text])
