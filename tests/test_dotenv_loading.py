"""Tests for load_dotenv_if_present() in config.py."""
from __future__ import annotations
import os
from pathlib import Path

import pytest

from claude_voice.config import load_dotenv_if_present


class TestLoadDotenvIfPresent:
    def test_missing_file_no_error(self, tmp_path: Path) -> None:
        """A missing .env file should not raise an exception."""
        absent = tmp_path / "nonexistent.env"
        assert not absent.exists()
        load_dotenv_if_present(path=absent)  # must not raise

    def test_missing_file_does_not_alter_env(self, tmp_path: Path, monkeypatch) -> None:
        """Existing env vars are unaffected when the file is absent."""
        monkeypatch.setenv("SENTINEL_VAR", "original")
        load_dotenv_if_present(path=tmp_path / "nonexistent.env")
        assert os.environ["SENTINEL_VAR"] == "original"

    def test_present_file_sets_var(self, tmp_path: Path, monkeypatch) -> None:
        """.env file with FOO=bar → os.environ['FOO'] == 'bar'."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")
        monkeypatch.delenv("FOO", raising=False)
        load_dotenv_if_present(path=env_file)
        assert os.environ.get("FOO") == "bar"

    def test_existing_env_var_not_overridden(self, tmp_path: Path, monkeypatch) -> None:
        """A key already in os.environ must NOT be overridden (override=False)."""
        env_file = tmp_path / ".env"
        env_file.write_text("MY_KEY=from_file\n")
        monkeypatch.setenv("MY_KEY", "pre_existing")
        load_dotenv_if_present(path=env_file)
        assert os.environ["MY_KEY"] == "pre_existing"

    def test_default_path_is_config_dir(self, monkeypatch, tmp_path: Path) -> None:
        """When path=None, the function targets CONFIG_DIR / '.env'."""
        import claude_voice.config as cfg_mod

        # Temporarily redirect CONFIG_DIR so we don't touch the real homedir.
        monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_DEFAULT_TEST=yes\n")
        monkeypatch.delenv("DOTENV_DEFAULT_TEST", raising=False)

        # Call with no path argument — should read from the patched CONFIG_DIR.
        cfg_mod.load_dotenv_if_present()
        assert os.environ.get("DOTENV_DEFAULT_TEST") == "yes"
