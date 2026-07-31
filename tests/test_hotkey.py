import pytest
from unittest.mock import MagicMock
from pynput import keyboard
from claude_voice.config import HotkeyConfig
from claude_voice.hotkey import HotkeyListener, HotkeyEvent, _parse_key


def test_parse_key_alt_r():
    assert _parse_key("alt_r") == keyboard.Key.alt_r


def test_parse_key_f1():
    assert _parse_key("f1") == keyboard.Key.f1


def test_parse_key_unknown_raises():
    with pytest.raises(ValueError):
        _parse_key("wat")


def test_ptt_down_up_events(mocker):
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    # simulate pynput callbacks
    listener._on_press(keyboard.Key.alt_r)
    listener._on_release(keyboard.Key.alt_r)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]


def test_ignores_non_ptt_keys():
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    listener._on_press(keyboard.Key.shift)
    listener._on_release(keyboard.Key.shift)
    assert events == []


def test_auto_repeat_ignored():
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    listener._on_press(keyboard.Key.alt_r)
    listener._on_press(keyboard.Key.alt_r)  # OS auto-repeat
    listener._on_press(keyboard.Key.alt_r)
    listener._on_release(keyboard.Key.alt_r)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]
