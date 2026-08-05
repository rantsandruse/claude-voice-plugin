from pathlib import Path
from unittest.mock import MagicMock
import pytest
from claude_voice.config import WhisperLocalConfig
from claude_voice.stt.whisper_local import WhisperLocalProvider


class FakeSegment:
    def __init__(self, text): self.text = text


def _mock_model(segments_text: list[str]):
    model = MagicMock()
    model.transcribe.return_value = ([FakeSegment(t) for t in segments_text], None)
    return model


def test_transcribe_concats_segments(mocker):
    fake = _mock_model([" Hello ", " there. "])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    result = p.transcribe(Path("/tmp/fake.wav"))
    assert result == "Hello there"  # normalized, trailing period stripped


def test_transcribe_filters_hallucination(mocker):
    fake = _mock_model(["Thanks for watching!"])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    assert p.transcribe(Path("/tmp/fake.wav")) == ""


def test_transcribe_empty_returns_empty(mocker):
    fake = _mock_model([])
    mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    assert p.transcribe(Path("/tmp/fake.wav")) == ""


def test_model_loaded_once(mocker):
    fake = _mock_model(["hi"])
    ctor = mocker.patch(
        "claude_voice.stt.whisper_local.WhisperModel",
        return_value=fake,
    )
    p = WhisperLocalProvider(WhisperLocalConfig())
    p.transcribe(Path("/tmp/f.wav"))
    p.transcribe(Path("/tmp/f.wav"))
    assert ctor.call_count == 1
