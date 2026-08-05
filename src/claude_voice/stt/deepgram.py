from __future__ import annotations
from pathlib import Path
import re
import httpx

from ..config import DeepgramConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS

_URL = "https://api.deepgram.com/v1/listen"


class DeepgramProvider:
    def __init__(self, config: DeepgramConfig, api_key: str):
        self._config = config
        self._api_key = api_key

    def transcribe(self, wav_path: Path) -> str:
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }
        params = {"model": self._config.model, "smart_format": "true"}
        with open(wav_path, "rb") as fp:
            data = fp.read()
        r = httpx.post(_URL, headers=headers, params=params, content=data, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Deepgram {r.status_code}: {r.text[:200]}")
        payload = r.json()
        try:
            transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError):
            return ""
        return self._post_process(transcript)

    @staticmethod
    def _post_process(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip().rstrip(".")
        if not text:
            return ""
        low = text.lower()
        for phrase in WHISPER_HALLUCINATION_PATTERNS:
            if phrase in low and len(text) < len(phrase) + 5:
                return ""
        return text
