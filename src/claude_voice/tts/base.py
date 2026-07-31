from __future__ import annotations
import subprocess
from typing import Protocol


class TTSProvider(Protocol):
    def speak(self, text: str) -> subprocess.Popen: ...
