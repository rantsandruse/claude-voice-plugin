import subprocess
import pytest
import respx
import httpx
from claude_voice.config import ElevenLabsConfig
from claude_voice.tts.elevenlabs import ElevenLabsProvider


@respx.mock
def test_speak_pipes_stream_to_afplay(mocker):
    route = respx.post(
        "https://api.elevenlabs.io/v1/text-to-speech/rachel/stream"
    ).mock(return_value=httpx.Response(200, content=b"MP3AUDIO"))

    handle = mocker.MagicMock(spec=subprocess.Popen)
    handle.stdin = mocker.MagicMock()
    handle.poll.return_value = None
    popen_mock = mocker.patch(
        "claude_voice.tts.elevenlabs.subprocess.Popen",
        return_value=handle,
    )

    p = ElevenLabsProvider(ElevenLabsConfig(voice_id="rachel"), api_key="k")
    handle = p.speak("hello")

    # afplay was started
    assert popen_mock.call_args[0][0] == ["afplay", "-"]
    # give the streaming thread a moment
    import time; time.sleep(0.1)
    handle.stdin.write.assert_called()  # bytes were streamed


@respx.mock
def test_speak_raises_on_non_2xx():
    respx.post("https://api.elevenlabs.io/v1/text-to-speech/rachel/stream").mock(
        return_value=httpx.Response(401, content=b"nope")
    )
    p = ElevenLabsProvider(ElevenLabsConfig(voice_id="rachel"), api_key="k")
    with pytest.raises(RuntimeError):
        p.speak("hello")


def test_speak_empty_raises():
    p = ElevenLabsProvider(ElevenLabsConfig(), api_key="k")
    with pytest.raises(ValueError):
        p.speak("")
