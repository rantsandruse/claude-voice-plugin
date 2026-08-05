from __future__ import annotations
from pathlib import Path
import io
import re
import wave
import httpx
import numpy as np

from ..config import DeepgramConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS

_URL = "https://api.deepgram.com/v1/listen"


class DeepgramProvider:
    def __init__(self, config: DeepgramConfig, api_key: str):
        self._config = config
        self._api_key = api_key

    def warmup(self) -> None:
        # No-op: nothing to preload for a cloud provider.
        return

    def transcribe(self, wav_path: Path) -> str:
        with open(wav_path, "rb") as fp:
            data = fp.read()
        return self._post_process(self._call(data))

    def transcribe_audio(self, audio: np.ndarray, sample_rate: int) -> str:
        """Hot path: encode float32 audio to WAV bytes in memory and POST."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            audio_i16 = np.clip(audio * 32768.0, -32768, 32767).astype(np.int16)
            w.writeframes(audio_i16.tobytes())
        return self._post_process(self._call(buf.getvalue()))

    def _call(self, wav_bytes: bytes) -> str:
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }
        params = {"model": self._config.model, "smart_format": "true"}
        r = httpx.post(_URL, headers=headers, params=params, content=wav_bytes, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Deepgram {r.status_code}: {r.text[:200]}")
        payload = r.json()
        try:
            return payload["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError):
            return ""

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
