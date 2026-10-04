from __future__ import annotations
from pathlib import Path
import wave
import numpy as np

from ..config import WhisperCppConfig
from ..text_cleaner import clean_transcript


def _load_model(config: WhisperCppConfig):
    from pywhispercpp.model import Model

    return Model(
        config.model,
        redirect_whispercpp_logs_to=None,  # whisper.cpp is chatty on stderr
        print_progress=False,
        print_realtime=False,
        # Each PTT press is a standalone utterance; same reasoning as
        # condition_on_previous_text=False in whisper_local.
        no_context=True,
        language=config.language,
    )


def _speech_only(audio: np.ndarray) -> np.ndarray | None:
    """Keep only the speech in *audio*, or None if there is none.

    Whisper invents text on silence ("[BLANK_AUDIO]", "Thank you"), and with
    auto-submit that text gets sent. This is the same silero VAD, with the
    same defaults, that faster-whisper's vad_filter=True applies, so both
    local backends treat silence identically.
    """
    from faster_whisper.vad import collect_chunks, get_speech_timestamps

    timestamps = get_speech_timestamps(audio)
    if not timestamps:
        return None
    chunks, _ = collect_chunks(audio, timestamps)
    return np.concatenate(chunks)


class WhisperCppProvider:
    def __init__(self, config: WhisperCppConfig):
        self._config = config
        self._model = None

    def _model_get(self):
        if self._model is None:
            self._model = _load_model(self._config)
        return self._model

    def warmup(self) -> None:
        # Loading also compiles the Metal shaders, which takes seconds on the
        # first run. Call the model directly: silence would be dropped by the
        # VAD and never reach the GPU.
        self._model_get().transcribe(np.zeros(16000, dtype=np.float32))

    def transcribe(self, wav_path: Path) -> str:
        with wave.open(str(wav_path), "rb") as w:
            sample_rate = w.getframerate()
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return self.transcribe_audio(audio.astype(np.float32) / 32768.0, sample_rate)

    def transcribe_audio(self, audio: np.ndarray, sample_rate: int) -> str:
        if sample_rate != 16000:
            raise ValueError(f"expected 16000 Hz audio, got {sample_rate}")
        speech = _speech_only(audio.astype(np.float32))
        if speech is None:
            return ""
        segments = self._model_get().transcribe(speech)
        return clean_transcript(" ".join(s.text.strip() for s in segments))
