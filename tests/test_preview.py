import threading
import time
import numpy as np
from claude_voice.preview import LivePreview, SAMPLE_RATE


class Feed:
    """Stands in for Recorder.snapshot(): audio that grows as 'time' passes."""
    def __init__(self):
        self.samples = 0
    def grow(self, seconds):
        self.samples += int(seconds * SAMPLE_RATE)
    def __call__(self):
        return np.zeros(self.samples, dtype=np.float32) if self.samples else None


def _wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _mk(feed, transcribe, **kw):
    shown, hidden = [], []
    p = LivePreview(feed, transcribe, shown.append, lambda: hidden.append(True),
                    interval=0.02, **kw)
    return p, shown, hidden


def test_shows_listening_then_transcripts_then_hides():
    feed = Feed()
    p, shown, hidden = _mk(feed, lambda a, abort: f"{len(a) // SAMPLE_RATE}s of speech")
    p.start()
    assert shown == ["Listening…"]
    feed.grow(1.0)
    assert _wait_for(lambda: "1s of speech" in shown)
    feed.grow(1.0)
    assert _wait_for(lambda: "2s of speech" in shown)
    p.stop()
    assert hidden == [True]


def test_skips_short_and_unchanged_audio():
    feed = Feed()
    calls = []
    p, _, _ = _mk(feed, lambda a, abort: calls.append(len(a)) or "x")
    p.start()
    feed.grow(0.2)  # under min_audio_s
    time.sleep(0.15)
    assert calls == []
    feed.grow(0.8)
    assert _wait_for(lambda: len(calls) == 1)
    time.sleep(0.15)  # no new audio -> no re-run
    assert len(calls) == 1
    p.stop()


def test_stop_cancels_in_flight_run_and_drops_its_text():
    feed = Feed()
    feed.grow(1.0)
    started = threading.Event()

    def slow(audio, abort):
        started.set()
        while not abort():
            time.sleep(0.005)
        return "late text"

    p, shown, _ = _mk(feed, slow)
    p.start()
    assert started.wait(2.0)
    t = time.monotonic()
    p.stop()
    assert time.monotonic() - t < 0.5
    assert "late text" not in shown


def test_long_recordings_preview_only_the_tail():
    feed = Feed()
    feed.grow(5.0)
    lengths = []
    p, shown, _ = _mk(feed, lambda a, abort: lengths.append(len(a)) or "tail", max_audio_s=2.0)
    p.start()
    assert _wait_for(lambda: lengths)
    p.stop()
    assert lengths[0] == 2 * SAMPLE_RATE
    assert "…tail" in shown


def test_transcribe_error_ends_preview_quietly():
    feed = Feed()
    feed.grow(1.0)
    p, shown, _ = _mk(feed, lambda a, abort: 1 / 0)
    p.start()
    time.sleep(0.1)
    p.stop()  # must not raise
    assert shown == ["Listening…"]
