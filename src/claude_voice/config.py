from __future__ import annotations
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import yaml

CONFIG_DIR = Path.home() / ".config" / "claude-voice"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Load ``~/.config/claude-voice/.env`` into *os.environ* without overriding.

    Silently does nothing when the file is absent or ``python-dotenv`` is not
    installed.  Pass an explicit *path* to override the default location (useful
    in tests).
    """
    dotenv_path = path if path is not None else CONFIG_DIR / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        return
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)


@dataclass(frozen=True)
class HotkeyConfig:
    ptt: str = "alt_r"
    replay: str = "cmd+shift+r"


@dataclass(frozen=True)
class WhisperLocalConfig:
    model: str = "small"
    device: str = "auto"
    language: str = "en"


@dataclass(frozen=True)
class DeepgramConfig:
    model: str = "nova-2"


@dataclass(frozen=True)
class STTConfig:
    provider: str = "whisper_local"
    whisper_local: WhisperLocalConfig = field(default_factory=WhisperLocalConfig)
    deepgram: DeepgramConfig = field(default_factory=DeepgramConfig)


@dataclass(frozen=True)
class ElevenLabsConfig:
    voice_id: str = "rachel"
    model: str = "eleven_turbo_v2_5"


@dataclass(frozen=True)
class SayConfig:
    voice: str = "Samantha"


@dataclass(frozen=True)
class TTSConfig:
    enabled: bool = True
    provider: str = "elevenlabs"
    mode: str = "prose"
    summary_threshold: int = 500
    elevenlabs: ElevenLabsConfig = field(default_factory=ElevenLabsConfig)
    say: SayConfig = field(default_factory=SayConfig)


@dataclass(frozen=True)
class FeedbackConfig:
    sounds: bool = True
    menu_bar: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "info"
    path: str = "~/.config/claude-voice/daemon.log"


@dataclass(frozen=True)
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _merge_dataclass(instance, overrides: dict):
    """Recursively override a frozen dataclass from a dict."""
    if not overrides:
        return instance
    new_values = {}
    for f in instance.__dataclass_fields__.values():
        if f.name in overrides:
            current = getattr(instance, f.name)
            override = overrides[f.name]
            if hasattr(current, "__dataclass_fields__") and isinstance(override, dict):
                new_values[f.name] = _merge_dataclass(current, override)
            else:
                new_values[f.name] = override
    return replace(instance, **new_values) if new_values else instance


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    defaults = Config()
    if not path.exists():
        return defaults
    with open(path) as fp:
        raw = yaml.safe_load(fp) or {}
    return _merge_dataclass(defaults, raw)


def secrets() -> dict[str, str | None]:
    return {
        "DEEPGRAM_API_KEY": os.environ.get("DEEPGRAM_API_KEY"),
        "ELEVENLABS_API_KEY": os.environ.get("ELEVENLABS_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
    }
