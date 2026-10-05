import subprocess
import threading
import time
from unittest.mock import MagicMock
from claude_voice.playback import PlaybackController


class FakeProc:
    """Behaves like a running say/afplay Popen: wait() blocks until the
    utterance finishes, is terminated, or is killed."""

    def __init__(self, stubborn: bool = False):
        self._done = threading.Event()
        self._stubborn = stubborn  # ignores SIGTERM

    def finish(self):
        self._done.set()

    def poll(self):
        return 0 if self._done.is_set() else None

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(cmd="say", timeout=timeout)
        return 0

    def terminate(self):
        if not self._stubborn:
            self._done.set()

    def kill(self):
        self._done.set()


def _proc(**kw):
    # wraps= records calls for assertions while delegating behavior.
    return MagicMock(wraps=FakeProc(**kw))


def _provider(*procs):
    provider = MagicMock()
    provider.speak.side_effect = list(procs)
    return provider


def _wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def _spoken(provider):
    return [c.args[0] for c in provider.speak.call_args_list]


def test_speak_calls_provider():
    provider = _provider(_proc())
    p = PlaybackController(provider)
    assert p.speak("hello", "id1") is True
    provider.speak.assert_called_once_with("hello")


def test_new_speech_waits_instead_of_interrupting():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("first", "id1")
    assert p.speak("second", "id2") is True
    time.sleep(0.05)
    h1.terminate.assert_not_called()
    assert _spoken(provider) == ["first"]  # second is waiting
    h1._mock_wraps.finish()
    assert _wait_for(lambda: _spoken(provider) == ["first", "second"])


def test_queue_plays_in_arrival_order():
    procs = [_proc() for _ in range(3)]
    provider = _provider(*procs)
    p = PlaybackController(provider)
    for i, text in enumerate(["one", "two", "three"]):
        p.speak(text, f"id{i}")
    for i in range(3):
        assert _wait_for(lambda: len(_spoken(provider)) == i + 1)
        procs[i]._mock_wraps.finish()
    assert _spoken(provider) == ["one", "two", "three"]


def test_is_playing_while_items_are_queued():
    h1, h2 = _proc(), _proc()
    p = PlaybackController(_provider(h1, h2))
    p.speak("first", "id1")
    p.speak("second", "id2")
    assert p.is_playing()
    h1._mock_wraps.finish()
    assert _wait_for(lambda: h2._mock_wraps.poll() is None and p.is_playing())
    h2._mock_wraps.finish()
    assert _wait_for(lambda: not p.is_playing())


def test_interrupt_terminates_and_drops_queue():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("first", "id1")
    p.speak("second", "id2")
    p.interrupt()
    h1.terminate.assert_called_once()
    time.sleep(0.05)
    assert _spoken(provider) == ["first"]  # queued item never starts
    assert not p.is_playing()


def test_speech_after_interrupt_plays_immediately():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("first", "id1")
    p.interrupt()
    p.speak("second", "id2")
    assert _spoken(provider) == ["first", "second"]


def test_interrupt_when_idle_is_noop():
    p = PlaybackController(_provider())
    p.interrupt()  # should not raise


def test_replay_last_speaks_stored_text():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("hello", "id1")
    p.interrupt()
    p.replay_last()
    assert _spoken(provider) == ["hello", "hello"]


def test_replay_cuts_in_rather_than_queueing():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("hello", "id1")
    p.replay_last()
    h1.terminate.assert_called_once()
    assert _spoken(provider) == ["hello", "hello"]


def test_replay_when_nothing_stored():
    p = PlaybackController(_provider())
    assert p.replay_last() is False


def test_falls_back_on_provider_error():
    provider = MagicMock()
    provider.speak.side_effect = RuntimeError("network down")
    fallback = _provider(_proc())
    p = PlaybackController(provider, fallback=fallback)
    assert p.speak("hi", "id1") is True
    fallback.speak.assert_called_once_with("hi")


def test_queued_item_that_fails_to_start_is_skipped():
    h1, h3 = _proc(), _proc()
    provider = MagicMock()
    provider.speak.side_effect = [h1, RuntimeError("bad text"), h3]
    p = PlaybackController(provider)
    p.speak("one", "id1")
    p.speak("two", "id2")
    p.speak("three", "id3")
    h1._mock_wraps.finish()
    assert _wait_for(lambda: _spoken(provider) == ["one", "two", "three"])
    assert p.is_playing()


def test_watchdog_terminates_stuck_subprocess_and_moves_on():
    """If a TTS subprocess is still alive at max_duration, kill it and play
    the next queued utterance."""
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider, max_duration_seconds=0.05)
    p.speak("stuck", "id1")
    p.speak("next", "id2")
    assert _wait_for(lambda: h1.terminate.called)
    assert _wait_for(lambda: _spoken(provider) == ["stuck", "next"])


def test_watchdog_cancelled_on_interrupt():
    """Interrupt cancels the watchdog so it doesn't fire against a dead proc."""
    handle = _proc()
    p = PlaybackController(_provider(handle), max_duration_seconds=0.05)
    p.speak("x", "id1")
    p.interrupt()  # cancels watchdog
    handle.reset_mock()
    time.sleep(0.15)  # if the watchdog had fired, terminate would be called again
    handle.terminate.assert_not_called()


def test_interrupt_escalates_to_kill_when_terminate_stalls():
    """terminate → wait → kill if the process refuses to die."""
    handle = _proc(stubborn=True)
    p = PlaybackController(_provider(handle))
    p.speak("x", "id1")
    p.interrupt()
    handle.terminate.assert_called_once()
    handle.kill.assert_called_once()


def test_interrupt_waits_for_clean_terminate():
    """When terminate succeeds fast, kill is not called."""
    handle = _proc()
    p = PlaybackController(_provider(handle))
    p.speak("x", "id1")
    p.interrupt()
    handle.terminate.assert_called_once()
    handle.kill.assert_not_called()


def test_clear_queue_drops_waiting_but_finishes_current():
    h1, h2 = _proc(), _proc()
    provider = _provider(h1, h2)
    p = PlaybackController(provider)
    p.speak("current", "id1")
    p.speak("stale", "id2")
    p.clear_queue()
    h1.terminate.assert_not_called()  # current sentence keeps playing
    h1._mock_wraps.finish()
    time.sleep(0.05)
    assert _spoken(provider) == ["current"]
    assert not p.is_playing()
