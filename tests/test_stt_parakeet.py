import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import numpy as np
from claude_voice.config import ParakeetConfig
from claude_voice.stt.parakeet import ParakeetProvider


def _patch_model(mocker, text):
    model = MagicMock()
    model.preprocessor_config = SimpleNamespace(sample_rate=16000)
    model.generate.return_value = [SimpleNamespace(text=text)]
    loader = mocker.patch("claude_voice.stt.parakeet._load_model", return_value=model)
    # Keep the test hermetic: no MLX needed to exercise the provider logic.
    mocker.patch.dict(sys.modules, {
        "mlx": MagicMock(), "mlx.core": MagicMock(),
        "parakeet_mlx": MagicMock(), "parakeet_mlx.audio": MagicMock(),
    })
    return model, loader


def test_transcribe_audio_cleans_text(mocker):
    _patch_model(mocker, "  Fix the bug in daemon.py.  ")
    p = ParakeetProvider(ParakeetConfig())
    assert p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000) == "Fix the bug in daemon.py"


def test_rejects_wrong_sample_rate(mocker):
    _patch_model(mocker, "hi")
    p = ParakeetProvider(ParakeetConfig())
    try:
        p.transcribe_audio(np.zeros(100, dtype=np.float32), 44100)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_model_loaded_once(mocker):
    _, loader = _patch_model(mocker, "hi")
    p = ParakeetProvider(ParakeetConfig())
    p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)
    p.transcribe_audio(np.zeros(16000, dtype=np.float32), 16000)
    assert loader.call_count == 1
