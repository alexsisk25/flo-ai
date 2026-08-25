"""macOS permission checks.

Global hotkeys and typing into other apps both require Accessibility. Without
it pynput raises nothing — the listener simply never fires. Flo used to
print "Hotkeys active" regardless, so the modal first-run failure looked like
a working app that ignored you. Everything here exists to make that legible.

Nothing in this module can *grant* a permission. Only the user can, in System
Settings. What we can do is know, say so, and open the right pane.
"""

import subprocess
import sys


def _warn(msg: str) -> None:
    """Permission checks that fail must SAY SO.

    Every bug that cost this project real time was a permission problem hidden
    behind a bare `except: pass`. A missing pyobjc framework made
    request_microphone() a no-op for weeks, so macOS was never asked for mic
    access, so Whisper transcribed silence and hallucinated. Nothing logged.
    """
    print(f"[permissions] {msg}", file=sys.stderr, flush=True)

# System Settings → Privacy & Security → Accessibility
_AX_PANE = ("x-apple.systempreferences:com.apple.preference.security"
            "?Privacy_Accessibility")


def _warm_pyobjc_constants() -> None:
    """Resolve AXIsProcessTrusted on the main thread, before anything races.

    pyobjc resolves framework constants lazily and its lookup table is not
    thread-safe: two threads asking for the same constant at once make one of
    them die with `KeyError: 'AXIsProcessTrusted'`. pynput's listener does
    exactly that from its own thread as it starts up. In tests it shows as a
    PytestUnhandledThreadExceptionWarning; in the app it would mean the hotkey
    listener thread dying at launch, leaving Flo running and deaf — the failure
    mode this project has already spent weeks on twice.

    Touching it once here, at import, single-threaded, makes the race
    impossible rather than unlikely.
    """
    try:
        from ApplicationServices import AXIsProcessTrusted
        AXIsProcessTrusted()
    except Exception as e:
        _warn(f"could not pre-resolve AXIsProcessTrusted "
              f"({type(e).__name__}: {e}); a hotkey listener thread may race "
              "on it at startup")


_warm_pyobjc_constants()


def accessibility_trusted() -> bool:
    """True if this process may post keyboard events and observe hotkeys."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception as e:
        # Not on macOS, or pyobjc missing. Don't block the app over a check,
        # but do not pretend this was a real "yes" either.
        _warn(f"could not check Accessibility ({type(e).__name__}: {e}); "
              "assuming granted — hotkeys may silently never fire")
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
    except Exception as e:
        _warn(f"could not show the Accessibility prompt "
              f"({type(e).__name__}: {e})")
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

    Requires pyobjc-framework-avfoundation, declared in pyproject.toml.
    Without it this call silently does nothing and macOS is never asked for
    mic access, which is how Flo spent weeks recording digital silence.
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
    except Exception as e:
        # THE original bug: pyobjc-framework-avfoundation was not declared as a
        # dependency, so this import raised, this handler swallowed it, macOS
        # was never asked, and Flo recorded silence for weeks. Never silent again.
        _warn(f"could not request Microphone access ({type(e).__name__}: {e}); "
              "recordings will be silent")


# AVAuthorizationStatus
_MIC_STATUS = {0: "not_requested", 1: "restricted", 2: "denied", 3: "granted"}


def microphone_status() -> str:
    """'granted' | 'denied' | 'restricted' | 'not_requested' | 'unknown'.

    Worth checking separately from Accessibility, because the failure is silent
    and deeply misleading: PortAudio happily "records" without mic permission,
    it just returns digital silence. Whisper then hallucinates on that silence —
    almost always the single word "You" — so the app looks like it heard you and
    got it catastrophically wrong, rather than like it never heard you at all.
    """
    try:
        import AVFoundation
        st = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio)
        return _MIC_STATUS.get(int(st), "unknown")
    except Exception as e:
        _warn(f"could not read Microphone status ({type(e).__name__}: {e})")
        return "unknown"


def summary() -> dict:
    """What the dashboard and --doctor report."""
    ok = accessibility_trusted()
    mic = microphone_status()
    return {
        "accessibility": ok,
        "microphone": mic,
        "mic_hint": None if mic in ("granted", "unknown") else (
            "Flo can open the mic but is recording silence. System Settings → "
            "Privacy & Security → Microphone. Then restart Flo."),
        "hint": None if ok else (
            "Flo needs Accessibility permission to use global hotkeys and "
            "type into other apps. System Settings → Privacy & Security → "
            "Accessibility. Restart Flo afterwards."),
    }
