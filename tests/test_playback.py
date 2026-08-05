import subprocess
from unittest.mock import MagicMock
from claude_voice.playback import PlaybackController


def _mock_provider(handle=None):
    provider = MagicMock()
    provider.speak.return_value = handle or MagicMock(spec=subprocess.Popen)
    return provider


def test_speak_calls_provider():
    handle = MagicMock(spec=subprocess.Popen)
    handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    assert p.speak("hello", "id1") is True
    provider.speak.assert_called_once_with("hello")


def test_speak_interrupts_previous():
    h1 = MagicMock(spec=subprocess.Popen); h1.poll.return_value = None
    h2 = MagicMock(spec=subprocess.Popen); h2.poll.return_value = None
    provider = MagicMock()
    provider.speak.side_effect = [h1, h2]
    p = PlaybackController(provider)
    p.speak("first", "id1")
    p.speak("second", "id2")
    h1.terminate.assert_called_once()


def test_interrupt_terminates():
    handle = MagicMock(spec=subprocess.Popen); handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    p.speak("x", "id1")
    p.interrupt()
    handle.terminate.assert_called_once()


def test_interrupt_when_idle_is_noop():
    p = PlaybackController(_mock_provider())
    p.interrupt()  # should not raise


def test_replay_last_speaks_stored_text():
    handle = MagicMock(spec=subprocess.Popen); handle.poll.return_value = None
    provider = _mock_provider(handle)
    p = PlaybackController(provider)
    p.speak("hello", "id1")
    p.interrupt()
    p.replay_last()
    assert provider.speak.call_count == 2
    assert provider.speak.call_args_list[1].args == ("hello",)


def test_replay_when_nothing_stored():
    p = PlaybackController(_mock_provider())
    assert p.replay_last() is False


def test_falls_back_on_provider_error():
    provider = MagicMock()
    provider.speak.side_effect = RuntimeError("network down")
    fallback = MagicMock()
    fallback_handle = MagicMock(spec=subprocess.Popen); fallback_handle.poll.return_value = None
    fallback.speak.return_value = fallback_handle
    p = PlaybackController(provider, fallback=fallback)
    assert p.speak("hi", "id1") is True
    fallback.speak.assert_called_once_with("hi")
