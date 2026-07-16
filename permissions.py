"""macOS permission checks.

Global hotkeys and typing into other apps both require Accessibility. Without
it pynput raises nothing — the listener simply never fires. Flo used to
print "Hotkeys active" regardless, so the modal first-run failure looked like
a working app that ignored you. Everything here exists to make that legible.

Nothing in this module can *grant* a permission. Only the user can, in System
Settings. What we can do is know, say so, and open the right pane.
"""

import subprocess

# System Settings → Privacy & Security → Accessibility
_AX_PANE = ("x-apple.systempreferences:com.apple.preference.security"
            "?Privacy_Accessibility")


def accessibility_trusted() -> bool:
    """True if this process may post keyboard events and observe hotkeys."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        # Not on macOS, or pyobjc missing. Don't block the app over a check.
        return True


def request_accessibility() -> bool:
    """Ask macOS to show its 'grant Accessibility' dialog, once.

    Returns the current trust state. macOS shows the prompt at most once per
    binary; after that the call is just a check.
    """
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return accessibility_trusted()


def open_accessibility_settings() -> None:
    """Deep-link straight to the pane the user needs."""
    subprocess.Popen(["open", _AX_PANE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def request_microphone() -> None:
    """Ask macOS for Microphone permission via AVFoundation.

    PortAudio/sounddevice never triggers the TCC prompt on its own — it just
    returns silence if the permission hasn't been granted. Calling this at
    startup ensures the system dialog appears on first launch and that
    Flo.app shows up in Privacy & Security → Microphone.

    Uses objc.loadBundle (pyobjc-core, already a dependency) to load
    AVFoundation directly — no extra package needed.
    """
    try:
        import AVFoundation
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
        if status == 0:  # AVAuthorizationStatusNotDetermined
            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVFoundation.AVMediaTypeAudio, lambda granted: None
            )
    except Exception:
        pass


def summary() -> dict:
    """What the dashboard and --doctor report."""
    ok = accessibility_trusted()
    return {
        "accessibility": ok,
        "hint": None if ok else (
            "Flo needs Accessibility permission to use global hotkeys and "
            "type into other apps. System Settings → Privacy & Security → "
            "Accessibility. Restart Flo afterwards."),
    }
