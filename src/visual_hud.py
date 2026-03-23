"""On-screen visual status HUD for VoiceTyper."""
from __future__ import annotations

import threading
from typing import Final

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSFontWeightSemibold,
    NSLeftTextAlignment,
    NSScreen,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect, NSString
from PyObjCTools.AppHelper import callAfter


class VisualHUD:
    """Bottom-center floating HUD to show current input state."""

    MIN_WIDTH: Final[float] = 152.0
    MAX_WIDTH: Final[float] = 206.0
    HEIGHT: Final[float] = 44.0
    BOTTOM_MARGIN: Final[float] = 34.0
    CORNER_RADIUS: Final[float] = 13.0
    DOT_SIZE: Final[float] = 8.0
    PAD_LEFT: Final[float] = 12.0
    PAD_RIGHT: Final[float] = 12.0
    DOT_GAP: Final[float] = 10.0
    LABEL_FONT_SIZE: Final[float] = 13.0
    BLINK_INTERVAL_SECS: Final[float] = 0.42
    BLINK_DIM_OPACITY: Final[float] = 0.32

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._window: NSWindow | None = None
        self._container: NSView | None = None
        self._dot: NSView | None = None
        self._label: NSTextField | None = None
        self._lock = threading.Lock()
        self._state_seq = 0
        self._hide_timer: threading.Timer | None = None
        self._blink_timer: threading.Timer | None = None
        self._blink_visible = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.hide()

    def show_recording(self) -> None:
        self._show("Recording...", kind="recording", auto_hide_secs=None)

    def show_transcribing(self) -> None:
        self._show("Transcribing...", kind="transcribing", auto_hide_secs=None)

    def show_done(self, label: str = "Done") -> None:
        self._show(label, kind="done", auto_hide_secs=1.0)

    def show_error(self, label: str = "Error") -> None:
        self._show(label, kind="error", auto_hide_secs=1.6)

    def hide(self) -> None:
        self._bump_state_seq()
        self._cancel_hide_timer()
        self._cancel_blink_timer()
        self._blink_visible = True
        callAfter(self._hide_on_main)

    def close(self) -> None:
        self.hide()
        callAfter(self._close_on_main)

    def _show(self, text: str, kind: str, auto_hide_secs: float | None) -> None:
        if not self._enabled:
            return
        seq = self._bump_state_seq()
        self._cancel_hide_timer()
        self._cancel_blink_timer()
        self._blink_visible = True
        callAfter(self._show_on_main, text, kind)
        if kind == "recording":
            self._schedule_blink(seq, self.BLINK_INTERVAL_SECS)
        if auto_hide_secs and auto_hide_secs > 0:
            self._schedule_hide(seq, auto_hide_secs)

    def _bump_state_seq(self) -> int:
        with self._lock:
            self._state_seq += 1
            return self._state_seq

    def _cancel_hide_timer(self) -> None:
        timer: threading.Timer | None = None
        with self._lock:
            if self._hide_timer is not None:
                timer = self._hide_timer
                self._hide_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_hide(self, seq: int, delay_secs: float) -> None:
        def _hide_if_current():
            with self._lock:
                if seq != self._state_seq:
                    return
            callAfter(self._hide_on_main)

        timer = threading.Timer(delay_secs, _hide_if_current)
        timer.daemon = True
        with self._lock:
            self._hide_timer = timer
        timer.start()

    def _cancel_blink_timer(self) -> None:
        timer: threading.Timer | None = None
        with self._lock:
            if self._blink_timer is not None:
                timer = self._blink_timer
                self._blink_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_blink(self, seq: int, delay_secs: float) -> None:
        def _blink_if_current():
            with self._lock:
                if seq != self._state_seq:
                    return
                self._blink_timer = None
            callAfter(self._toggle_blink_on_main, seq)

        timer = threading.Timer(delay_secs, _blink_if_current)
        timer.daemon = True
        with self._lock:
            self._blink_timer = timer
        timer.start()

    def _ensure_window_on_main(self) -> None:
        if self._window is not None and self._label is not None:
            return

        frame = NSMakeRect(0.0, 0.0, self.MIN_WIDTH, self.HEIGHT)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(False)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(NSFloatingWindowLevel)
        window.setReleasedWhenClosed_(False)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        container = NSView.alloc().initWithFrame_(NSMakeRect(0.0, 0.0, self.MIN_WIDTH, self.HEIGHT))
        container.setWantsLayer_(True)
        container_layer = container.layer()
        if container_layer is not None:
            container_layer.setCornerRadius_(self.CORNER_RADIUS)
            container_layer.setMasksToBounds_(True)
            container_layer.setBorderWidth_(1.0)
            container_layer.setBorderColor_(
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).CGColor()
            )
            container_layer.setBackgroundColor_(self._fill_color("recording").CGColor())

        dot_y = (self.HEIGHT - self.DOT_SIZE) / 2.0
        dot = NSView.alloc().initWithFrame_(NSMakeRect(self.PAD_LEFT, dot_y, self.DOT_SIZE, self.DOT_SIZE))
        dot.setWantsLayer_(True)
        dot_layer = dot.layer()
        if dot_layer is not None:
            dot_layer.setCornerRadius_(self.DOT_SIZE / 2.0)
            dot_layer.setMasksToBounds_(True)
            dot_layer.setBackgroundColor_(self._accent_color("recording").CGColor())
            dot_layer.setOpacity_(1.0)

        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                self.PAD_LEFT + self.DOT_SIZE + self.DOT_GAP,
                0.0,
                self.MIN_WIDTH - (self.PAD_LEFT + self.DOT_SIZE + self.DOT_GAP) - self.PAD_RIGHT,
                self.HEIGHT,
            )
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(NSLeftTextAlignment)
        label.setFont_(NSFont.systemFontOfSize_weight_(self.LABEL_FONT_SIZE, NSFontWeightSemibold))
        label.setTextColor_(self._text_color("recording"))

        container.addSubview_(dot)
        container.addSubview_(label)
        window.setContentView_(container)
        window.orderOut_(None)

        self._window = window
        self._container = container
        self._dot = dot
        self._label = label

    def _fill_color(self, kind: str):
        if kind == "recording":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.79, 0.92, 0.84, 0.95
            )
        if kind == "transcribing":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.24, 0.20, 0.12, 0.90
            )
        if kind == "done":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.11, 0.21, 0.16, 0.90
            )
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.25, 0.12, 0.14, 0.90
        )

    def _accent_color(self, kind: str):
        if kind == "recording":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.20, 0.58, 0.34, 1.0
            )
        if kind == "transcribing":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.98, 0.72, 0.28, 1.0
            )
        if kind == "done":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.32, 0.86, 0.52, 1.0
            )
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.99, 0.46, 0.50, 1.0
        )

    def _text_color(self, kind: str):
        if kind == "recording":
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.12, 0.28, 0.18, 0.98
            )
        return NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.95)

    def _position_window_on_main(self) -> None:
        if self._window is None:
            return
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.visibleFrame()
        window_frame = self._window.frame()
        x = frame.origin.x + (frame.size.width - window_frame.size.width) / 2.0
        y = frame.origin.y + self.BOTTOM_MARGIN
        self._window.setFrame_display_(NSMakeRect(x, y, window_frame.size.width, self.HEIGHT), False)

    def _text_size(self, text: str):
        if self._label is None:
            font = NSFont.systemFontOfSize_weight_(self.LABEL_FONT_SIZE, NSFontWeightSemibold)
        else:
            font = self._label.font()
        attrs = {NSFontAttributeName: font}
        return NSString.stringWithString_(text).sizeWithAttributes_(attrs)

    def _layout_for_text_on_main(self, text: str) -> None:
        if self._window is None or self._container is None or self._dot is None or self._label is None:
            return

        text_size = self._text_size(text)
        target_width = (
            self.PAD_LEFT
            + self.DOT_SIZE
            + self.DOT_GAP
            + text_size.width
            + self.PAD_RIGHT
        )
        target_width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, target_width))

        dot_x = self.PAD_LEFT
        dot_y = (self.HEIGHT - self.DOT_SIZE) / 2.0
        label_h = max(16.0, text_size.height + 1.0)
        label_y = (self.HEIGHT - label_h) / 2.0
        label_x = dot_x + self.DOT_SIZE + self.DOT_GAP
        label_w = target_width - label_x - self.PAD_RIGHT

        self._window.setContentSize_((target_width, self.HEIGHT))
        self._container.setFrame_(NSMakeRect(0.0, 0.0, target_width, self.HEIGHT))
        self._dot.setFrame_(NSMakeRect(dot_x, dot_y, self.DOT_SIZE, self.DOT_SIZE))
        self._label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))

    def _show_on_main(self, text: str, kind: str) -> None:
        self._ensure_window_on_main()
        if self._window is None or self._container is None or self._dot is None or self._label is None:
            return
        self._label.setStringValue_(text)
        self._layout_for_text_on_main(text)
        container_layer = self._container.layer()
        if container_layer is not None:
            container_layer.setBackgroundColor_(self._fill_color(kind).CGColor())
        dot_layer = self._dot.layer()
        if dot_layer is not None:
            dot_layer.setBackgroundColor_(self._accent_color(kind).CGColor())
            if kind != "recording":
                dot_layer.setOpacity_(1.0)
        self._label.setTextColor_(self._text_color(kind))
        self._position_window_on_main()
        self._window.orderFrontRegardless()

    def _toggle_blink_on_main(self, seq: int) -> None:
        with self._lock:
            if seq != self._state_seq:
                return
        if self._dot is None:
            return
        dot_layer = self._dot.layer()
        if dot_layer is None:
            return

        self._blink_visible = not self._blink_visible
        target_opacity = 1.0 if self._blink_visible else self.BLINK_DIM_OPACITY
        dot_layer.setOpacity_(target_opacity)
        self._schedule_blink(seq, self.BLINK_INTERVAL_SECS)

    def _hide_on_main(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)

    def _close_on_main(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
            self._container = None
            self._dot = None
            self._label = None
