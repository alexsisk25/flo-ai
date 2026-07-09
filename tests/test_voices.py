"""Narration voice detection.

macOS hides its good voices behind a download almost nobody knows about, so
users conclude local narration simply sounds like a robot. Walnut notices and
says so. It cannot install them — they are Apple-licensed with no supported
programmatic installer — and Siri's voices never appear in `say -v '?'` at all.
"""

import pytest

import voices

# Real `say -v '?'` output. Note the shapes that broke the original parser:
# a name containing spaces and parens followed by a SINGLE space, and a
# numeric region code.
SAY_OUTPUT = """\
Albert                  en_US    # Hello! My name is Albert.
Ava (Premium)           en_US    # Hello! My name is Ava.
Eddy (English (US)) en_US    # Hello! My name is Eddy.
Evan (Enhanced)         en_US    # Hello! My name is Evan.
Majed                   ar_001   # Hi.
Mónica                  es_ES    # Hola.
Paulina (Premium)       es_MX    # Hola.
Samantha                en_US    # Hello! My name is Samantha.
"""


@pytest.fixture(autouse=True)
def _clear_voice_cache():
    voices.invalidate_cache()
    yield
    voices.invalidate_cache()


@pytest.fixture
def say(monkeypatch):
    """Install fake `say -v '?'` output, and count how often it's shelled out."""
    calls = {"n": 0}

    def _install(stdout: str):
        class R:
            pass
        r = R()
        r.stdout = stdout

        def fake_run(*a, **k):
            calls["n"] += 1
            return r
        monkeypatch.setattr(voices.subprocess, "run", fake_run)
        return calls
    return _install


# ---------------------------------------------------------------- parsing

def test_parses_every_voice_including_the_awkward_ones(say):
    say(SAY_OUTPUT)
    parsed = voices.list_voices()
    assert len(parsed) == 8, [v["name"] for v in parsed]

    names = {v["name"] for v in parsed}
    # a name with spaces + nested parens, separated by ONE space. The original
    # regex demanded `\s{2,}` and silently dropped 109 of this Mac's 184 voices.
    assert "Eddy (English (US))" in names
    # numeric region code
    assert any(v["locale"] == "ar_001" for v in parsed)
    assert any(v["locale"] == "es_ES" for v in parsed)


def test_quality_tiers():
    assert voices.quality("Ava (Premium)") == voices.PREMIUM
    assert voices.quality("Evan (Enhanced)") == voices.ENHANCED
    assert voices.quality("Samantha") == voices.STANDARD
    assert voices.quality("ava (premium)") == voices.PREMIUM   # case-insensitive


def test_list_voices_survives_say_being_missing(monkeypatch):
    def boom(*a, **k):
        raise OSError("no say here")
    monkeypatch.setattr(voices.subprocess, "run", boom)
    assert voices.list_voices() == []


# ----------------------------------------------------------------- status

def test_ok_when_a_premium_voice_is_selected(say):
    say(SAY_OUTPUT)
    s = voices.status(selected="Ava (Premium)")
    assert s["ok"] is True and s["reason"] is None


def test_ok_when_an_enhanced_voice_is_selected(say):
    say(SAY_OUTPUT)
    assert voices.status(selected="Evan (Enhanced)")["ok"] is True


def test_nudge_when_good_voices_exist_but_a_default_is_selected(say):
    say(SAY_OUTPUT)
    s = voices.status(selected="", language="en")
    assert s["ok"] is False
    assert s["reason"] == "not_selected"
    assert "Ava (Premium)" in s["suggestions"]


def test_suggestions_match_the_users_language(say):
    """A Spanish Premium voice doesn't help someone narrating English."""
    say(SAY_OUTPUT)
    en = voices.status(selected="", language="en")["suggestions"]
    es = voices.status(selected="", language="es")["suggestions"]
    assert "Ava (Premium)" in en and "Paulina (Premium)" not in en
    assert "Paulina (Premium)" in es


def test_nudge_to_download_when_nothing_good_is_installed(say):
    say("Albert   en_US    # Hi.\nSamantha en_US    # Hi.\n")
    s = voices.status(selected="")
    assert s["ok"] is False
    assert s["reason"] == "none_installed"
    assert "Manage Voices" in s["hint"]
    assert s["suggestions"] == []


def test_no_nagging_when_say_is_unavailable(monkeypatch):
    monkeypatch.setattr(voices, "list_voices", lambda: [])
    assert voices.status(selected="")["ok"] is True


def test_falls_back_to_any_good_voice_when_language_has_none(say):
    """Only Spanish premium installed, user narrates English: still offer it
    rather than telling them to download something they already have."""
    say("Albert  en_US   # Hi.\nPaulina (Premium)  es_MX  # Hola.\n")
    s = voices.status(selected="", language="en")
    assert s["reason"] == "not_selected"
    assert s["suggestions"] == ["Paulina (Premium)"]


# ------------------------------------------------- the selected voice is gone

def test_a_selected_voice_that_is_uninstalled_is_not_reported_as_fine(say):
    """`say` does not error on an unknown voice — it silently substitutes the
    system default (verified: exit 0, byte-identical output). Judging quality
    from the stored NAME meant Walnut reported voice_ok while the user heard
    the robot."""
    say(SAY_OUTPUT)
    s = voices.status(selected="Lee (Premium)")   # never installed here
    assert s["ok"] is False
    assert s["reason"] == "missing"
    assert "no longer installed" in s["hint"]
    assert "Lee (Premium)" in s["hint"]
    # and it points at what IS available
    assert "Ava (Premium)" in s["suggestions"]


def test_missing_voice_with_nothing_good_installed_offers_the_download(say):
    say("Albert   en_US    # Hi.\nSamantha en_US    # Hi.\n")
    s = voices.status(selected="Lee (Premium)")
    assert s["reason"] == "missing"
    assert "Manage Voices" in s["hint"]
    assert s["suggestions"] == []


def test_an_installed_premium_voice_is_still_fine(say):
    say(SAY_OUTPUT)
    assert voices.status(selected="Ava (Premium)")["ok"] is True


def test_a_missing_standard_voice_is_also_flagged(say):
    """Not just Premium: any selected voice that vanished means macOS is
    substituting silently."""
    say(SAY_OUTPUT)
    assert voices.status(selected="Tom")["reason"] == "missing"


def test_every_status_carries_a_title_for_the_banner(say):
    say(SAY_OUTPUT)
    for sel in ("Lee (Premium)", "", "Ava (Premium)"):
        assert "title" in voices.status(selected=sel)


# ------------------------------------------------------------------- cache

def test_voice_list_is_cached(say):
    calls = say(SAY_OUTPUT)
    voices.list_voices()
    voices.list_voices()
    voices.list_voices()
    assert calls["n"] == 1, "say -v '?' costs ~380ms; it must not run per call"


def test_cache_expires(say, monkeypatch):
    calls = say(SAY_OUTPUT)
    clock = {"t": 1000.0}
    monkeypatch.setattr(voices.time, "monotonic", lambda: clock["t"])
    voices.list_voices()
    clock["t"] += voices.CACHE_TTL_SECS + 1
    voices.list_voices()
    assert calls["n"] == 2


def test_opening_the_voice_pane_invalidates_the_cache(say, monkeypatch):
    """The one moment the list is likely to change is when we send the user to
    install a voice."""
    calls = say(SAY_OUTPUT)
    monkeypatch.setattr(voices.subprocess, "Popen", lambda *a, **k: None)
    voices.list_voices()
    voices.open_voice_settings()
    voices.list_voices()
    assert calls["n"] == 2


def test_status_does_not_shell_out_twice(say):
    calls = say(SAY_OUTPUT)
    voices.status(selected="")
    voices.status(selected="")
    assert calls["n"] == 1


# ------------------------------------------------------------- pane naming

@pytest.mark.parametrize("mac_ver,expected", [
    ("26.5.1", "Read & Speak"),      # renamed, and dropped from the sidebar
    ("26.0", "Read & Speak"),
    ("15.4", "Spoken Content"),
    ("14.0", "Spoken Content"),
])
def test_pane_name_tracks_the_macos_rename(monkeypatch, mac_ver, expected):
    monkeypatch.setattr(voices.platform, "mac_ver", lambda: (mac_ver, "", ""))
    assert voices.pane_name() == expected


def test_pane_name_survives_an_unparseable_version(monkeypatch):
    monkeypatch.setattr(voices.platform, "mac_ver", lambda: ("", "", ""))
    assert "Read & Speak" in voices.pane_name()   # mentions both, guesses neither


def test_download_hint_names_the_pane_that_exists(monkeypatch, say):
    """Telling a user to click something not in their sidebar is worse than
    saying nothing. macOS 26 has no 'Spoken Content'."""
    say("Albert   en_US    # Hi.\n")
    monkeypatch.setattr(voices.platform, "mac_ver", lambda: ("26.5.1", "", ""))
    hint = voices.status(selected="")["hint"]
    assert "Read & Speak" in hint and "Spoken Content" not in hint

    monkeypatch.setattr(voices.platform, "mac_ver", lambda: ("14.0", "", ""))
    hint = voices.status(selected="")["hint"]
    assert "Spoken Content" in hint and "Read & Speak" not in hint


# ----------------------------------------------------------------- server

def test_status_endpoint_exposes_the_voice_verdict(client):
    d = client.get("/api/status").get_json()
    assert "voice_ok" in d and "voice_reason" in d and "voice_suggestions" in d


def test_voices_endpoint_reports_quality(client):
    for v in client.get("/api/voices").get_json():
        assert v["quality"] in (voices.PREMIUM, voices.ENHANCED, voices.STANDARD)
        assert v["name"] and v["locale"]
