from __future__ import annotations
from pathlib import Path
import re

from faster_whisper import WhisperModel

from ..config import WhisperLocalConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS


class WhisperLocalProvider:
    def __init__(self, config: WhisperLocalConfig):
        self._config = config
        self._model: WhisperModel | None = None

    def _model_get(self) -> WhisperModel:
        if self._model is None:
            device = "auto" if self._config.device == "auto" else self._config.device
            compute_type = "int8" if device != "cuda" else "float16"
            self._model = WhisperModel(
                self._config.model, device=device, compute_type=compute_type
            )
        return self._model

    def transcribe(self, wav_path: Path) -> str:
        segments, _ = self._model_get().transcribe(
            str(wav_path), language=self._config.language
        )
        raw = " ".join(seg.text.strip() for seg in segments).strip()
        return self._post_process(raw)

    @staticmethod
    def _post_process(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = text.rstrip(".")
        if not text:
            return ""
        low = text.lower()
        for phrase in WHISPER_HALLUCINATION_PATTERNS:
            if phrase in low and len(text) < len(phrase) + 5:
                return ""
        return text
