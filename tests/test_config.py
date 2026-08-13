from pathlib import Path
import textwrap
import pytest
from claude_voice.config import load_config, secrets, Config


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.hotkey.ptt == "alt_r"
    assert cfg.stt.provider == "whisper_local"
    assert cfg.stt.whisper_local.model == "small"
    assert cfg.tts.enabled is True
    assert cfg.tts.provider == "elevenlabs"
    assert cfg.tts.mode == "summary"
    assert cfg.tts.summary_threshold == 500
    assert cfg.feedback.sounds is True
    assert cfg.feedback.menu_bar is True


def test_load_config_partial_overrides_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        stt:
          provider: deepgram
        tts:
          mode: summary
    """))
    cfg = load_config(p)
    assert cfg.stt.provider == "deepgram"
    assert cfg.tts.mode == "summary"
    # unchanged defaults
    assert cfg.hotkey.ptt == "alt_r"
    assert cfg.tts.provider == "elevenlabs"


def test_secrets_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = secrets()
    assert s["DEEPGRAM_API_KEY"] == "dg-key"
    assert s["ELEVENLABS_API_KEY"] == "el-key"
    assert s["ANTHROPIC_API_KEY"] is None


def test_config_is_frozen():
    cfg = load_config(Path("/nonexistent"))
    with pytest.raises((AttributeError, Exception)):
        cfg.hotkey.ptt = "cmd"  # should be immutable
