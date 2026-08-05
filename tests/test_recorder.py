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


def test_recording_over_300ms_returns_audio(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.5)  # 500ms
    result = rec.stop()
    assert result is not None
    audio, sr = result
    assert sr == 16000
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert len(audio) == int(0.5 * 16000)


def test_stop_to_wav_writes_file(fake_stream, tmp_path):
    rec = Recorder(output_dir=tmp_path)
    rec.start()
    fake_stream["stream"].feed(0.5)
    path = rec.stop_to_wav()
    assert path is not None
    assert path.exists()
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2


def test_stop_before_start_returns_none(tmp_path):
    rec = Recorder(output_dir=tmp_path)
    assert rec.stop() is None


def test_start_retries_after_portaudio_error(mocker, tmp_path):
    """First InputStream() throws PortAudioError; recorder resets PortAudio
    and retries. Second attempt succeeds. handle_hotkey never sees an error."""
    import sounddevice as sd

    holder = {}
    call_count = {"n": 0}

    def make(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise sd.PortAudioError("simulated stale state", -9986)
        stream = FakeInputStream(
            samplerate=kwargs["samplerate"],
            channels=kwargs["channels"],
            dtype=kwargs["dtype"],
            callback=kwargs["callback"],
        )
        holder["stream"] = stream
        return stream

    mocker.patch("claude_voice.recorder.sd.InputStream", side_effect=make)
    term = mocker.patch("claude_voice.recorder.sd._terminate")
    init = mocker.patch("claude_voice.recorder.sd._initialize")

    rec = Recorder(output_dir=tmp_path)
    rec.start()  # should not raise

    assert call_count["n"] == 2
    term.assert_called_once()
    init.assert_called_once()
    assert "stream" in holder
