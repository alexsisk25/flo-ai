"""macOS narration voices, and whether the user is stuck on a bad one.

Every Mac ships with decades-old formant voices selected by default. It also
ships the *ability* to download modern neural ones — Enhanced and Premium —
free, offline, from System Settings. Almost nobody knows they exist, so almost
everybody concludes that local text-to-speech sounds like a robot.

Walnut cannot install them: they are Apple-licensed components with no
supported programmatic installer. What it can do is notice, say so, and open
the right pane. (Siri's voices are walled off from `say` entirely — they never
appear in `say -v '?'` — so Premium is the ceiling for this code path.)
"""

import platform
import re
import subprocess
import time

# The pane that holds "System voice → Manage Voices". Its ANCHOR has been
# stable across releases; only Apple's name for it changes, so the deep link
# below still lands correctly on macOS 26 even though the sidebar no longer
# says "Spoken Content".
_VOICE_PANE = ("x-apple.systempreferences:com.apple.preference.universalaccess"
               "?TextToSpeech")


def _pane_name() -> str:
    """What the pane is called on THIS macOS.

    macOS 26 renamed Accessibility → "Spoken Content" to "Read & Speak" and
    dropped it from the sidebar list. Telling a user to click something that
    isn't there is worse than saying nothing.
    """
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return "Spoken Content (or Read & Speak)"
    return "Read & Speak" if major >= 26 else "Spoken Content"

# `say -v '?'` lines look like:
#   Tom                    en_US    # Hello! My name is Tom.
#   Ava (Premium)          en_US    # Hello! My name is Ava.
#   Eddy (English (US))    en_US    # Hello! My name is Eddy.   <- ONE space
#   Majed                  ar_001   # ...                       <- numeric region
# Anchor on the locale, not on run-length of spaces: the old `\s{2,}` rule
# silently dropped 109 of this Mac's 184 voices from the Settings dropdown.
_LINE = re.compile(r"^(.+?)\s+([a-z]{2,3}(?:_(?:[A-Z]{2}|[0-9]{3}))?)\s+#\s*(.*)$")

PREMIUM = "premium"
ENHANCED = "enhanced"
STANDARD = "standard"


def quality(name: str) -> str:
    lowered = name.lower()
    if "(premium)" in lowered:
        return PREMIUM
    if "(enhanced)" in lowered:
        return ENHANCED
    return STANDARD


# `say -v '?'` costs ~380ms — a real subprocess, enumerating 184 voices. It was
# being run on every /api/status and every /api/voices, so the Settings page
# paid ~760ms before painting, and the dashboard re-paid it every 3 seconds
# while the speech model downloaded. The list changes when a user installs a
# voice, which happens about twice in a machine's life. Cache it.
CACHE_TTL_SECS = 60
_cache: dict = {"voices": None, "at": 0.0}


def invalidate_cache() -> None:
    """Called when we send the user off to install voices — the one moment the
    list is actually likely to change."""
    _cache["voices"] = None


def _read_voices() -> list[dict]:
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    voices = []
    for line in out.splitlines():
        m = _LINE.match(line)
        if m:
            name = m.group(1).strip()
            voices.append({"name": name, "locale": m.group(2),
                           "sample": m.group(3), "quality": quality(name)})
    return voices


def list_voices() -> list[dict]:
    """Installed voices, cached for CACHE_TTL_SECS."""
    now = time.monotonic()
    if _cache["voices"] is None or now - _cache["at"] > CACHE_TTL_SECS:
        _cache["voices"] = _read_voices()
        _cache["at"] = now
    return _cache["voices"]


def _good(v: dict) -> bool:
    return v["quality"] in (PREMIUM, ENHANCED)


def _download_hint() -> str:
    return ("macOS ships far better narration voices for free — they're just "
            f"not installed. System Settings → Accessibility → {_pane_name()} "
            "→ System voice → Manage Voices. Look for (Premium) or (Enhanced), "
            "then pick it here.")


def status(selected: str = "", language: str = "en") -> dict:
    """Is this user going to hear something decent?

    Four outcomes, and they need different advice:

      ok             — a Premium/Enhanced voice is selected AND installed.
      missing        — the selected voice is gone. `say` does not complain: it
                       silently falls back to the system default, so Walnut
                       would otherwise report "fine" while the user hears the
                       robot. Judging quality from the stored *name* alone was
                       exactly the kind of unearned claim this feature exists
                       to stamp out.
      not_selected   — good voices are installed but the user is on a default.
      none_installed — no good voice exists on this Mac. Send them to download.
    """
    voices = list_voices()
    if not voices:                       # `say` missing; not our problem to nag
        return {"ok": True, "reason": None, "title": None,
                "hint": None, "suggestions": []}

    lang = (language or "en").split("_")[0].lower() or "en"
    good = [v for v in voices if _good(v)]
    # A Spanish Premium voice doesn't help someone narrating English.
    usable = [v for v in good if v["locale"].lower().startswith(lang)] or good
    suggestions = [v["name"] for v in usable[:5]]
    installed = {v["name"] for v in voices}

    if selected and selected not in installed:
        return {
            "ok": False,
            "reason": "missing",
            "title": "Your narration voice is gone",
            "hint": (f"“{selected}” is no longer installed, so macOS is quietly "
                     "using its default voice instead. Pick another on the "
                     "Settings page."
                     if usable else
                     f"“{selected}” is no longer installed, so macOS is quietly "
                     f"using its default voice instead. {_download_hint()}"),
            "suggestions": suggestions,
        }

    if selected and quality(selected) in (PREMIUM, ENHANCED):
        return {"ok": True, "reason": None, "title": None,
                "hint": None, "suggestions": []}

    if usable:
        return {
            "ok": False,
            "reason": "not_selected",
            "title": "Walnut sounds robotic?",
            "hint": ("You have high-quality voices installed but Walnut is "
                     "using a default one. Pick one on the Settings page."),
            "suggestions": suggestions,
        }
    return {
        "ok": False,
        "reason": "none_installed",
        "title": "Walnut sounds robotic?",
        "hint": _download_hint(),
        "suggestions": [],
    }


def pane_name() -> str:
    """Public: what to call the voice pane in UI copy on this macOS."""
    return _pane_name()


def open_voice_settings() -> None:
    """Deep-link to the pane that downloads voices."""
    # They're about to install one. Don't serve a stale list for a minute.
    invalidate_cache()
    subprocess.Popen(["open", _VOICE_PANE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
