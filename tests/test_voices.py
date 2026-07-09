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


@pytest.fixture
def say(monkeypatch):
    def _install(stdout: str):
        class R:
            pass
        r = R()
        r.stdout = stdout
        monkeypatch.setattr(voices.subprocess, "run", lambda *a, **k: r)
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


# ----------------------------------------------------------------- server

def test_status_endpoint_exposes_the_voice_verdict(client):
    d = client.get("/api/status").get_json()
    assert "voice_ok" in d and "voice_reason" in d and "voice_suggestions" in d


def test_voices_endpoint_reports_quality(client):
    for v in client.get("/api/voices").get_json():
        assert v["quality"] in (voices.PREMIUM, voices.ENHANCED, voices.STANDARD)
        assert v["name"] and v["locale"]
