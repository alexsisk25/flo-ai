"""Floating recording indicator — a dark pill shown while dictating,
with the Flo mark, live audio-level dots, and a pulsing record dot.
Styled after the macOS dictation indicator.

All AppKit calls are marshalled to the main thread with AppHelper.callAfter,
so show()/hide()/set_level() are safe from any thread.
"""

import time
from pathlib import Path

import AppKit
import Quartz
from PyObjCTools import AppHelper

STATIC = Path(__file__).resolve().parent / "static"

W, H = 196, 54
N_BARS = 5
PILL_BG = (0.11, 0.11, 0.12, 0.96)
DOT_DIM = (0.34, 0.34, 0.36, 1.0)
DOT_LIT = (0.85, 0.85, 0.88, 1.0)
REC = (0.20, 0.70, 0.84, 1.0)   # teal accent (matches the Flo brand)


def _color(r, g, b, a):
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a).CGColor()


class Overlay:
    def __init__(self):
        self._visible = False
        self._last_level = 0.0
        self._built = False
        AppHelper.callAfter(self._build)

    # ------------------------------------------------------------ UI build

    def _build(self):
        screen = AppKit.NSScreen.mainScreen().frame()
        x = screen.origin.x + (screen.size.width - W) / 2
        y = screen.origin.y + 140  # just above the Dock
        rect = AppKit.NSMakeRect(x, y, W, H)

        style = (AppKit.NSWindowStyleMaskBorderless
                 | AppKit.NSWindowStyleMaskNonactivatingPanel)
        panel = AppKit.NSPanel.alloc(
        ).initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False)
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary)

        root = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, W, H))
        root.setWantsLayer_(True)
        root.layer().setBackgroundColor_(_color(*PILL_BG))
        root.layer().setCornerRadius_(16.0)
        panel.setContentView_(root)

        # Flo mark, left
        img = AppKit.NSImage.alloc().initByReferencingFile_(
            str(STATIC / "flo-overlay.png"))
        iv = AppKit.NSImageView.alloc().initWithFrame_(
            AppKit.NSMakeRect(16, (H - 28) / 2, 28, 28))
        iv.setImage_(img)
        iv.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
        root.addSubview_(iv)

        # level dots, center
        self._bars = []
        for i in range(N_BARS):
            bar = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(66 + i * 15, (H - 8) / 2, 8, 8))
            bar.setWantsLayer_(True)
            bar.layer().setBackgroundColor_(_color(*DOT_DIM))
            bar.layer().setCornerRadius_(4.0)
            root.addSubview_(bar)
            self._bars.append(bar)

        # pulsing record dot, right
        dot = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(W - 34, (H - 18) / 2, 18, 18))
        dot.setWantsLayer_(True)
        dot.layer().setBackgroundColor_(_color(*REC))
        dot.layer().setCornerRadius_(9.0)
        root.addSubview_(dot)
        self._dot = dot

        self._panel = panel
        self._built = True
        if self._visible:  # show() raced ahead of the build
            self._show_main()

    def _pulse(self):
        anim = Quartz.CABasicAnimation.animationWithKeyPath_("opacity")
        anim.setFromValue_(1.0)
        anim.setToValue_(0.35)
        anim.setDuration_(0.7)
        anim.setAutoreverses_(True)
        anim.setRepeatCount_(1e9)
        self._dot.layer().addAnimation_forKey_(anim, "pulse")

    # ------------------------------------------------------------ API

    def show(self):
        self._visible = True
        AppHelper.callAfter(self._show_main)

    def hide(self):
        self._visible = False
        AppHelper.callAfter(self._hide_main)

    def set_level(self, rms: float):
        """Called from the audio thread; throttled to ~20 fps."""
        now = time.monotonic()
        if now - self._last_level < 0.05 or not self._visible:
            return
        self._last_level = now
        lit = min(N_BARS, int(min(1.0, rms * 14) * N_BARS + 0.5))
        AppHelper.callAfter(self._set_bars_main, lit)

    # ------------------------------------------------------------ main-thread

    def _show_main(self):
        if not self._built:
            return
        self._set_bars_main(0)
        self._panel.orderFrontRegardless()
        self._pulse()

    def _hide_main(self):
        if not self._built:
            return
        self._dot.layer().removeAllAnimations()
        self._panel.orderOut_(None)

    def _set_bars_main(self, lit: int):
        for i, bar in enumerate(self._bars):
            bar.layer().setBackgroundColor_(
                _color(*(DOT_LIT if i < lit else DOT_DIM)))
