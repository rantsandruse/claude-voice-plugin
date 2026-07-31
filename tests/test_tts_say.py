import subprocess
import pytest
from claude_voice.config import SayConfig
from claude_voice.tts.say import SayProvider


def test_speak_starts_subprocess(mocker):
    popen_mock = mocker.patch(
        "claude_voice.tts.say.subprocess.Popen",
        return_value=mocker.MagicMock(spec=subprocess.Popen),
    )
    p = SayProvider(SayConfig(voice="Samantha"))
    handle = p.speak("hello")
    popen_mock.assert_called_once()
    args = popen_mock.call_args[0][0]
    assert args == ["say", "-v", "Samantha", "hello"]
    assert handle is popen_mock.return_value


def test_speak_empty_raises():
    p = SayProvider(SayConfig())
    with pytest.raises(ValueError):
        p.speak("")

    with pytest.raises(ValueError):
        p.speak("   ")
