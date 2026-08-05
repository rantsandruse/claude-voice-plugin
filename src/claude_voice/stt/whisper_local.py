from __future__ import annotations
from pathlib import Path
import re
import numpy as np

from faster_whisper import WhisperModel

from ..config import WhisperLocalConfig
from ..text_cleaner import WHISPER_HALLUCINATION_PATTERNS


# Tuning applied to every transcribe call:
# - beam_size=1: greedy decoding is 2-3x faster than the default beam_size=5,
#   with negligible quality loss on short PTT utterances.
# - vad_filter=True: silero-VAD strips leading/trailing silence, so the model
#   spends inference time on actual speech.
# - condition_on_previous_text=False: each PTT press is a standalone utterance,
#   so there's no previous context to condition on. Disabling avoids drift.
_TRANSCRIBE_KWARGS = dict(
    beam_size=1,
    vad_filter=True,
    condition_on_previous_text=False,
)


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

    def warmup(self) -> None:
        """Force the model weights to load. Called from daemon startup so the
        first PTT press doesn't eat the multi-second cold-load penalty."""
        self._model_get()

    def transcribe(self, wav_path: Path) -> str:
        segments, _ = self._model_get().transcribe(
            str(wav_path), language=self._config.language, **_TRANSCRIBE_KWARGS,
        )
        raw = " ".join(seg.text.strip() for seg in segments).strip()
        return self._post_process(raw)

    def transcribe_audio(self, audio: np.ndarray, sample_rate: int) -> str:
        """Hot path used by the daemon PTT flow. faster_whisper accepts a
        float32 numpy array directly, so we skip WAV encode/decode entirely."""
        # faster_whisper assumes 16 kHz. Recorder is fixed at 16 kHz, so this
        # is defensive — mismatch would be a caller bug, not something to hide.
        if sample_rate != 16000:
            raise ValueError(f"expected 16000 Hz audio, got {sample_rate}")
        segments, _ = self._model_get().transcribe(
            audio, language=self._config.language, **_TRANSCRIBE_KWARGS,
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
