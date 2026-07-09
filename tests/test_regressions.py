"""Regression tests. Every test here is a bug Walnut actually shipped.

Run with:  uv run --group dev pytest -q
"""

import os
import sqlite3
import subprocess

import numpy as np
import pytest


def _open_fds() -> int:
    out = subprocess.run(["lsof", "-p", str(os.getpid())],
                         capture_output=True, text=True).stdout
    return out.count("\n")


# ------------------------------------------------------------------- storage

def test_connections_are_closed(db):
    """`with _conn() as c` used sqlite3's context manager, which commits but
    never closes. Hundreds of dashboard polls leaked file descriptors."""
    before = _open_fds()
    for _ in range(300):
        db.get("stt_model")
    assert _open_fds() - before < 5


def test_wal_and_indexes(db):
    con = sqlite3.connect(db.DB_PATH)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='history'")}
    assert "idx_history_ts" in idx
    con.close()


def test_history_search_escapes_like_wildcards(db):
    db.history_add("dictation", "literally 100% done", 1.0)
    db.history_add("dictation", "unrelated", 1.0)
    assert len(db.history_list(q="100%")) == 1
    assert len(db.history_list(q="%")) == 1        # not a match-everything


def test_history_limit_is_clamped(db):
    for i in range(5):
        db.history_add("dictation", f"row {i}", 1.0)
    assert len(db.history_list(limit=10**9)) == 5  # no unbounded fetch
    assert len(db.history_list(limit=-1)) == 1


# ---------------------------------------------------------------- vocabulary

def test_backslash_in_fixup_does_not_break_dictation(db):
    """A fix-up containing \\1 or \\t was passed to re.sub as a template.
    It raised re.PatternError inside a worker thread, so *every* subsequent
    transcription silently produced nothing."""
    from core import Vocabulary

    db.replacements_add("num", r"\1")
    db.replacements_add("path", r"C:\temp")
    out, _ = Vocabulary.apply("num and path here")
    assert out == r"\1 and C:\temp here"


def test_snippet_still_expands(db):
    from core import Vocabulary

    db.snippets_add("insert my sig", "me@example.com")
    # matching ignores case and trailing punctuation
    out, used = Vocabulary.apply("Insert my sig.")
    assert (out, used) == ("me@example.com", True)


def test_duplicate_snippet_trigger_first_one_wins(db):
    """Nothing stops two snippets sharing a trigger; the lower id wins because
    snippets_list() orders by trigger then returns on the first match. Pinned
    here so the behaviour is a decision rather than an accident."""
    from core import Vocabulary

    db.snippets_add("dup trigger", "first")
    db.snippets_add("dup trigger", "second")
    out, used = Vocabulary.apply("dup trigger")
    assert (out, used) == ("first", True)


# ------------------------------------------------------------------ settings

@pytest.mark.parametrize("key,value,ok", [
    ("tts_rate", "210", True),
    ("tts_rate", "fast", False),
    ("tts_rate", "9999", False),
    ("typing_wpm", "0", False),
    ("typing_wpm", "60", True),
    ("stt_backend", "bogus", False),
    ("stt_backend", "auto", True),
    ("stt_language", "english", False),
    ("stt_language", "en", True),
    ("hotkey_speak", "garbage", False),
    ("hotkey_speak", "<ctrl>+<alt>+s", True),
])
def test_validate_setting(db, key, value, ok):
    if ok:
        db.validate_setting(key, value)
    else:
        with pytest.raises(ValueError):
            db.validate_setting(key, value)


def test_unknown_setting_rejected(db):
    with pytest.raises(ValueError):
        db.validate_setting("rm_rf", "1")


def test_get_valid_heals_a_poisoned_database(db):
    """A database hand-edited (or written by an older Walnut) must not be able
    to take the process down on the next launch."""
    db.set_setting("hotkey_speak", "garbage")
    db.set_setting("tts_rate", "fast")
    assert db.get_valid("hotkey_speak") == db.DEFAULTS["hotkey_speak"]
    assert db.get_valid("tts_rate") == db.DEFAULTS["tts_rate"]


def test_hotkey_manager_survives_unparseable_combo(db):
    """hotkeys.start() ran in WalnutApp.__init__. A bad stored combo raised,
    the process died, and launchd's KeepAlive respawned it forever."""
    import core

    db.set_setting("hotkey_speak", "garbage")
    hk = core.HotkeyManager(core.Core())
    hk.start()                       # must not raise
    assert hk.listener is not None   # and must leave working hotkeys
    hk.stop()


# --------------------------------------------------------------------- audio

def test_audio_filenames_are_unique(db):
    """Second-resolution names collided: two dictations in one second wrote the
    same file, and deleting either unlinked the survivor's recording."""
    import core

    paths = {core.Core._save_audio(np.zeros(1600, dtype=np.float32))
             for _ in range(3)}
    assert len(paths) == 3


# -------------------------------------------------------------------- server

def test_bad_input_is_400_not_500(client):
    assert client.get("/api/history?limit=abc").status_code == 400
    assert client.put("/api/snippets/1", json={"expansion": "x"}).status_code == 400
    assert client.put("/api/settings", json={"tts_rate": "fast"}).status_code == 400


def test_rejected_hotkey_does_not_persist(client, db):
    before = db.get("hotkey_speak")
    assert client.put("/api/settings", json={"hotkey_speak": "garbage"}).status_code == 400
    assert db.get("hotkey_speak") == before        # written only after validating
    import server
    assert server.HOTKEYS.listener is not None     # listener survived


def test_valid_settings_round_trip(client, db):
    assert client.put("/api/settings", json={"tts_rate": "240"}).status_code == 200
    assert db.get("tts_rate") == "240"


def test_non_loopback_host_is_refused(client):
    """Any web page can POST to 127.0.0.1, and DNS rebinding can point an
    attacker's domain here. A Host check defeats both."""
    assert client.post("/api/speech/stop",
                       headers={"Host": "evil.example.com"}).status_code == 403
    assert client.post("/api/speech/stop",
                       headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.post("/api/speech/stop").status_code == 200


def test_system_endpoint_reports_hardware(client):
    d = client.get("/api/system").get_json()
    assert d["backend"] in ("mlx", "faster-whisper")
    assert len(d["models"]) == 6
    assert sum(m["recommended"] for m in d["models"]) == 1


def test_port_in_use_detection():
    import socket

    import server
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)
    assert server.port_in_use(port) is True
    s.close()
    assert server.port_in_use(port) is False
