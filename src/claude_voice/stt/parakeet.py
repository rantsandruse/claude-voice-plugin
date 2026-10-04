from __future__ import annotations
from pathlib import Path
import numpy as np

from ..config import ParakeetConfig
from ..text_cleaner import clean_transcript


def _load_model(config: ParakeetConfig):
    from parakeet_mlx import from_pretrained

    return from_pretrained(config.model)


class ParakeetProvider:
    """NVIDIA Parakeet via MLX (Apple Silicon GPU). Batch for now; the model
    also supports chunked streaming (model.transcribe_stream) for later."""

    def __init__(self, config: ParakeetConfig):
        self._config = config
        self._model = None

    def _model_get(self):
        if self._model is None:
            self._model = _load_model(self._config)
        return self._model

    def warmup(self) -> None:
        self.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)

    def transcribe(self, wav_path: Path) -> str:
        return clean_transcript(self._model_get().transcribe(str(wav_path)).text)

    def transcribe_audio(self, audio: np.ndarray, sample_rate: int) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        model = self._model_get()
        expected = model.preprocessor_config.sample_rate
        if sample_rate != expected:
            raise ValueError(f"expected {expected} Hz audio, got {sample_rate}")
        mel = get_logmel(mx.array(audio.astype(np.float32)), model.preprocessor_config)
        return clean_transcript(model.generate(mel)[0].text)
