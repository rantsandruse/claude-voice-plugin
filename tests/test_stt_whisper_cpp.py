from unittest.mock import MagicMock
import numpy as np
from claude_voice.config import WhisperCppConfig
from claude_voice.stt.whisper_cpp import WhisperCppProvider


class FakeSegment:
    def __init__(self, text): self.text = text


def _patch_model(mocker, segments_text):
    model = MagicMock()
    model.transcribe.return_value = [FakeSegment(t) for t in segments_text]
    loader = mocker.patch("claude_voice.stt.whisper_cpp._load_model", return_value=model)
    # Treat all test audio as speech; VAD behavior has its own tests below.
    mocker.patch("claude_voice.stt.whisper_cpp._speech_only", side_effect=lambda a: a)
    return model, loader


def test_transcribe_audio_concats_and_cleans(mocker):
    _patch_model(mocker, [" Hello ", " there. "])
    p = WhisperCppProvider(WhisperCppConfig())
    assert p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000) == "Hello there"


def test_filters_hallucination(mocker):
    _patch_model(mocker, ["Thank you for watching."])
    p = WhisperCppProvider(WhisperCppConfig())
    assert p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000) == ""


def test_rejects_wrong_sample_rate(mocker):
    _patch_model(mocker, ["hi"])
    p = WhisperCppProvider(WhisperCppConfig())
    try:
        p.transcribe_audio(np.zeros(100, dtype=np.float32), 44100)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_model_loaded_once(mocker):
    _, loader = _patch_model(mocker, ["hi"])
    p = WhisperCppProvider(WhisperCppConfig())
    p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)
    p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)
    assert loader.call_count == 1


def test_silence_skips_model_entirely(mocker):
    model, _ = _patch_model(mocker, ["Thank you"])
    mocker.patch("claude_voice.stt.whisper_cpp._speech_only", return_value=None)
    p = WhisperCppProvider(WhisperCppConfig())
    assert p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000) == ""
    model.transcribe.assert_not_called()


def test_only_speech_is_sent_to_model(mocker):
    model, _ = _patch_model(mocker, ["hi"])
    speech = np.ones(8000, dtype=np.float32)
    mocker.patch("claude_voice.stt.whisper_cpp._speech_only", return_value=speech)
    WhisperCppProvider(WhisperCppConfig()).transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)
    assert model.transcribe.call_args.args[0] is speech


def test_blank_audio_tag_is_dropped(mocker):
    _patch_model(mocker, ["[BLANK_AUDIO]"])
    p = WhisperCppProvider(WhisperCppConfig())
    assert p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000) == ""


def test_real_vad_rejects_digital_silence():
    # Unmocked: exercises the actual silero model shipped with faster-whisper.
    from claude_voice.stt.whisper_cpp import _speech_only
    assert _speech_only(np.zeros(2 * 16000, dtype=np.float32)) is None
