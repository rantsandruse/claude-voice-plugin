from __future__ import annotations
from pathlib import Path
from typing import Callable
import threading
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
        # The whisper.cpp context isn't safe to share across threads; the live
        # preview and the final transcription take turns.
        self._lock = threading.Lock()

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
        return self._run(audio, abort=None)

    def transcribe_preview(self, audio: np.ndarray, should_abort: Callable[[], bool]) -> str:
        """Best-effort transcript of a recording still in progress.
        *should_abort* cancels the run once the key is released; the final
        transcription then runs on the full clip as usual."""
        return self._run(audio, abort=should_abort)

    def _run(self, audio: np.ndarray, abort: Callable[[], bool] | None) -> str:
        speech = _speech_only(audio.astype(np.float32))
        if speech is None:
            return ""
        with self._lock:
            if abort is not None and abort():
                return ""
            segments = self._model_get().transcribe(speech, abort_callback=abort)
        return clean_transcript(" ".join(s.text.strip() for s in segments))
