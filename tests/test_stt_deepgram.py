from pathlib import Path
import pytest
import respx
import httpx
from claude_voice.config import DeepgramConfig
from claude_voice.stt.deepgram import DeepgramProvider


@pytest.fixture
def wav_file(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF....WAVEfmt " + b"\x00" * 100)
    return p


@respx.mock
def test_transcribe_success(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={
            "results": {
                "channels": [{"alternatives": [{"transcript": "hello world."}]}]
            }
        })
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == "hello world"


@respx.mock
def test_transcribe_filters_hallucination(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={
            "results": {
                "channels": [{"alternatives": [{"transcript": "Thanks for watching"}]}]
            }
        })
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == ""


@respx.mock
def test_transcribe_raises_on_non_2xx(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(401, json={"err": "bad key"})
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    with pytest.raises(RuntimeError):
        p.transcribe(wav_file)


@respx.mock
def test_transcribe_empty_result(wav_file):
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json={"results": {"channels": []}})
    )
    p = DeepgramProvider(DeepgramConfig(), api_key="k")
    assert p.transcribe(wav_file) == ""
