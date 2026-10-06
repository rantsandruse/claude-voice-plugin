import threading
import time
import numpy as np
from claude_voice.endpoint import EndpointDetector, SAMPLE_RATE, silero_speech


class Clock:
    """A recording that grows by `step` seconds of audio per snapshot, with
    speech wherever `speech_at(t)` is true."""
    def __init__(self, speech_at, step=0.1):
        self.t = 0.0
        self.step = step
        self.speech_at = speech_at

    def snapshot(self):
        self.t += self.step
        return np.zeros(int(self.t * SAMPLE_RATE), dtype=np.float32)

    def speech(self, window):
        # Map the window back to absolute time and report speech regions.
        dur = len(window) / SAMPLE_RATE
        start = self.t - dur
        regions, cur = [], None
        for i in range(int(dur * 100)):
            t = start + i / 100
            if self.speech_at(t) and cur is None:
                cur = t - start
            if not self.speech_at(t) and cur is not None:
                regions.append((cur, t - start)); cur = None
        if cur is not None:
            regions.append((cur, dur))
        return regions


def _run(clock, **kw):
    ended = []
    done = threading.Event()
    det = EndpointDetector(clock.snapshot, lambda r: (ended.append((r, round(clock.t, 1))), done.set()),
                           interval=0.001, speech=clock.speech, **kw)
    det.start()
    assert done.wait(5.0)
    det.stop()
    return ended


def test_ends_after_trailing_silence():
    clock = Clock(lambda t: 0.5 <= t < 3.0)
    [(reason, at)] = _run(clock, silence_s=1.2)
    assert reason == "silence"
    assert 4.1 <= at <= 4.4  # speech ended at 3.0 s, plus 1.2 s of quiet


def test_short_pauses_do_not_end_it():
    # Two 0.6 s pauses mid-dictation, then a real stop at 6 s.
    talking = lambda t: 0.5 <= t < 6.0 and not (2.0 <= t < 2.6 or 4.0 <= t < 4.6)
    [(reason, at)] = _run(Clock(talking), silence_s=1.2)
    assert reason == "silence" and at >= 7.1


def test_no_speech_times_out():
    [(reason, at)] = _run(Clock(lambda t: False), no_speech_timeout_s=2.0)
    assert reason == "no_speech" and 2.0 <= at <= 2.2


def test_late_start_within_timeout_is_kept():
    # Starts talking at 3 s with a 5 s timeout: must wait for the speech.
    [(reason, at)] = _run(Clock(lambda t: 3.0 <= t < 4.0), no_speech_timeout_s=5.0, silence_s=1.0)
    assert reason == "silence" and at >= 5.0


def test_max_duration_caps_endless_speech():
    [(reason, at)] = _run(Clock(lambda t: True), max_s=3.0)
    assert reason == "max" and 3.0 <= at <= 3.2


def test_stop_prevents_callback():
    ended = []
    det = EndpointDetector(lambda: None, ended.append, interval=0.01, speech=lambda a: [])
    det.start()
    det.stop()
    time.sleep(0.05)
    assert ended == []


def test_missing_audio_still_times_out():
    ended = []
    done = threading.Event()
    det = EndpointDetector(lambda: None, lambda r: (ended.append(r), done.set()),
                           no_speech_timeout_s=0.1, interval=0.01, speech=lambda a: [])
    det.start()
    assert done.wait(2.0)
    assert ended == ["no_speech"]


def test_silero_finds_no_speech_in_silence():
    assert silero_speech(np.zeros(2 * SAMPLE_RATE, dtype=np.float32)) == []
