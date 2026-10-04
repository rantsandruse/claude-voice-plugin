from __future__ import annotations

from AppKit import (
    NSBackingStoreBuffered,
    NSBox,
    NSBoxCustom,
    NSColor,
    NSEvent,
    NSFont,
    NSLineBreakByTruncatingHead,
    NSMakeRect,
    NSPanel,
    NSPointInRect,
    NSScreen,
    NSStatusWindowLevel,
    NSTextAlignmentCenter,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from PyObjCTools.AppHelper import callAfter

_MAX_WIDTH = 900
_HEIGHT = 44
_BOTTOM_GAP = 28   # above the Dock / bottom of the visible area
_PADDING = 16


class PreviewOverlay:
    """Caption-style bar at the bottom center of the screen the mouse is on.

    Never becomes key or main, ignores the mouse, and floats over full-screen
    apps, so the focused terminal stays focused and the release-time paste
    lands exactly where it does without the overlay. All methods are safe to
    call from any thread; AppKit work is marshalled to the main thread.
    """

    def __init__(self) -> None:
        self._panel = None
        self._label = None

    def show(self, text: str) -> None:
        callAfter(self._show_main, text)

    def hide(self) -> None:
        callAfter(self._hide_main)

    def _build(self) -> None:
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _MAX_WIDTH, _HEIGHT),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setOpaque_(False)
        panel.setHasShadow_(True)
        panel.setBackgroundColor_(NSColor.clearColor())

        # NSBox draws the rounded translucent background itself; going via a
        # CALayer would mean handing PyObjC a raw CGColorRef.
        content = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, _MAX_WIDTH, _HEIGHT))
        content.setBoxType_(NSBoxCustom)
        content.setBorderWidth_(0.0)
        content.setCornerRadius_(12.0)
        content.setFillColor_(NSColor.colorWithCalibratedWhite_alpha_(0.1, 0.85))
        content.setContentViewMargins_((0, 0))
        panel.setContentView_(content)

        label = NSTextField.labelWithString_("")
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(16.0))
        label.setAlignment_(NSTextAlignmentCenter)
        # Long dictation: keep the newest words visible, elide the start.
        label.setLineBreakMode_(NSLineBreakByTruncatingHead)
        label.setMaximumNumberOfLines_(1)
        content.addSubview_(label)

        self._panel, self._label = panel, label

    def _place(self) -> None:
        mouse = NSEvent.mouseLocation()
        screen = next(
            (s for s in NSScreen.screens() if NSPointInRect(mouse, s.frame())),
            NSScreen.mainScreen(),
        )
        area = screen.visibleFrame()  # excludes the Dock and menu bar
        width = min(_MAX_WIDTH, area.size.width * 0.7)
        x = area.origin.x + (area.size.width - width) / 2
        y = area.origin.y + _BOTTOM_GAP
        self._panel.setFrame_display_(NSMakeRect(x, y, width, _HEIGHT), True)
        line_h = self._label.intrinsicContentSize().height
        self._label.setFrame_(
            NSMakeRect(_PADDING, (_HEIGHT - line_h) / 2, width - 2 * _PADDING, line_h)
        )

    def _show_main(self, text: str) -> None:
        if self._panel is None:
            self._build()
        if not self._panel.isVisible():
            self._place()  # re-pick the screen once per press, not per update
        self._label.setStringValue_(text)
        self._panel.orderFrontRegardless()  # shows without activating

    def _hide_main(self) -> None:
        if self._panel is not None:
            self._panel.orderOut_(None)
