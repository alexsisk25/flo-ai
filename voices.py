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

import re
import subprocess

# System Settings → Accessibility → Spoken Content
_VOICE_PANE = ("x-apple.systempreferences:com.apple.preference.universalaccess"
               "?TextToSpeech")

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


def list_voices() -> list[dict]:
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


def _good(v: dict) -> bool:
    return v["quality"] in (PREMIUM, ENHANCED)


def status(selected: str = "", language: str = "en") -> dict:
    """Is this user going to hear something decent?

    Three outcomes, and they need different advice:

      ok             — a Premium/Enhanced voice is selected. Say nothing.
      not_selected   — good voices are installed but the user is on a default.
      none_installed — no good voice exists on this Mac. Send them to download.
    """
    voices = list_voices()
    if not voices:                       # `say` missing; not our problem to nag
        return {"ok": True, "reason": None, "hint": None, "suggestions": []}

    if selected and quality(selected) in (PREMIUM, ENHANCED):
        return {"ok": True, "reason": None, "hint": None, "suggestions": []}

    lang = (language or "en").split("_")[0].lower() or "en"
    good = [v for v in voices if _good(v)]
    # A Spanish Premium voice doesn't help someone narrating English.
    in_lang = [v for v in good if v["locale"].lower().startswith(lang)]
    usable = in_lang or good

    if usable:
        return {
            "ok": False,
            "reason": "not_selected",
            "hint": ("You have high-quality voices installed but Walnut is "
                     "using a default one. Pick one on the Settings page."),
            "suggestions": [v["name"] for v in usable[:5]],
        }
    return {
        "ok": False,
        "reason": "none_installed",
        "hint": ("macOS ships far better narration voices for free — they're "
                 "just not installed. System Settings → Accessibility → "
                 "Spoken Content → System Voice → Manage Voices. Look for "
                 "(Premium) or (Enhanced)."),
        "suggestions": [],
    }


def open_voice_settings() -> None:
    """Deep-link to the pane that downloads voices."""
    subprocess.Popen(["open", _VOICE_PANE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
