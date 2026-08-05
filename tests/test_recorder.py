import wave
import numpy as np
import pytest
from claude_voice.recorder import Recorder


class FakeInputStream:
    """Simulates sounddevice.InputStream with an injected callback."""
    def __init__(self, samplerate, channels, dtype, callback, blocksize=0):
        self.callback = callback
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self._active = False

    def start(self): self._active = True
    def stop(self): self._active = False
    def close(self): pass

    def feed(self, seconds: float):
        n = int(self.samplerate * seconds)
        frames = np.zeros((n, self.channels), dtype=self.dtype)
        self.callback(frames, n, None, None)


@pytest.fixture
def fake_stream(mocker):
    holder = {}
    def make(*args, **kwargs):
        stream = FakeInputStream(
            samplerate=kwargs["samplerate"],
            channels=kwargs["channels"],
            dtype=kwargs["dtype"],
            callback=kwargs["callback"],
        )
        holder["stream"] = stream
        return stream
    mocker.patch("claude_voice.recorder.sd.InputStream", side_effect=make)
    return holder


def test_recording_under_300ms_discarded(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.1)  # 100ms
    assert rec.stop() is None


def test_recording_over_300ms_written(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.5)  # 500ms
    path = rec.stop()
    assert path is not None
    assert path.exists()
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2  # 16-bit


def test_stop_before_start_returns_none(tmp_path):
    rec = Recorder(output_dir=tmp_path)
    assert rec.stop() is None
