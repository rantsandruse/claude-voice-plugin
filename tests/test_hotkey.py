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


def _press_release(listener, held_s, mocker):
    clock = mocker.patch("claude_voice.hotkey.time.monotonic")
    clock.return_value = 100.0
    listener._on_press(keyboard.Key.alt_r)
    clock.return_value = 100.0 + held_s
    listener._on_release(keyboard.Key.alt_r)


def test_quick_release_is_a_tap(mocker):
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append, max_tap_s=0.3)
    _press_release(listener, 0.1, mocker)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.TAP_UP]


def test_long_hold_is_push_to_talk(mocker):
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append, max_tap_s=0.3)
    _press_release(listener, 1.5, mocker)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]


def test_tap_detection_off_reports_release(mocker):
    events = []
    listener = HotkeyListener(HotkeyConfig(ptt="alt_r"), on_event=events.append)
    _press_release(listener, 0.05, mocker)
    assert events == [HotkeyEvent.PTT_DOWN, HotkeyEvent.PTT_UP]
