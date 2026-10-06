from __future__ import annotations
from enum import Enum, auto
from typing import Callable
import time
from pynput import keyboard

from .config import HotkeyConfig


class HotkeyEvent(Enum):
    PTT_DOWN = auto()
    PTT_UP = auto()
    # Released within the tap window: the daemon keeps recording hands-free.
    TAP_UP = auto()


def _parse_key(name: str):
    name = name.lower()
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        raise ValueError(f"unknown key name: {name}")


class HotkeyListener:
    def __init__(
        self,
        config: HotkeyConfig,
        on_event: Callable[[HotkeyEvent], None],
        max_tap_s: float | None = None,
    ):
        """*max_tap_s*: releases within this many seconds are reported as
        TAP_UP instead of PTT_UP. None disables tap detection."""
        self._ptt = _parse_key(config.ptt)
        self._on_event = on_event
        self._max_tap_s = max_tap_s
        self._listener: keyboard.Listener | None = None
        self._is_down = False
        self._down_at = 0.0

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        if key != self._ptt:
            return
        if self._is_down:
            return
        self._is_down = True
        self._down_at = time.monotonic()
        self._on_event(HotkeyEvent.PTT_DOWN)

    def _on_release(self, key) -> None:
        if key != self._ptt:
            return
        if not self._is_down:
            return
        self._is_down = False
        held = time.monotonic() - self._down_at
        if self._max_tap_s is not None and held < self._max_tap_s:
            self._on_event(HotkeyEvent.TAP_UP)
        else:
            self._on_event(HotkeyEvent.PTT_UP)
