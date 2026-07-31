from __future__ import annotations
from pathlib import Path
from typing import Protocol


class STTProvider(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...
