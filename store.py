"""SQLite storage for Walnut: settings, dictionary, snippets, history, stats."""

import sqlite3
import time
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "walnut.db"
RECORDINGS = HERE / "recordings"

DEFAULTS = {
    "tts_voice": "",
    "tts_rate": "210",
    "stt_model": "mlx-community/whisper-large-v3-turbo",
    "stt_language": "en",
    "typing_wpm": "60",
    "hotkey_speak": "<ctrl>+<alt>+s",
    "hotkey_dictate": "<ctrl>+<alt>+<space>",
    "snippets_enabled": "1",
    "port": "8765",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY, word TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS replacements (
    id INTEGER PRIMARY KEY, wrong TEXT NOT NULL, right TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY, trigger TEXT NOT NULL, expansion TEXT NOT NULL,
    uses INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,             -- 'dictation' | 'readback'
    ts REAL NOT NULL,               -- unix seconds
    text TEXT NOT NULL,
    words INTEGER NOT NULL,
    duration REAL NOT NULL,         -- seconds
    snippet INTEGER DEFAULT 0,      -- 1 if a snippet expanded
    audio_path TEXT);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    RECORDINGS.mkdir(exist_ok=True)
    with _conn() as c:
        c.executescript(SCHEMA)
        fresh = c.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
    if fresh:
        _seed_from_config()


def _seed_from_config() -> None:
    """First run: import the old config.toml so nothing is lost."""
    cfg = {}
    cfg_path = HERE / "config.toml"
    if cfg_path.exists():
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)
    settings = dict(DEFAULTS)
    tts, stt, hot = cfg.get("tts", {}), cfg.get("stt", {}), cfg.get("hotkeys", {})
    if tts.get("voice") is not None:
        settings["tts_voice"] = str(tts.get("voice", ""))
    if tts.get("rate"):
        settings["tts_rate"] = str(tts["rate"])
    if stt.get("model"):
        settings["stt_model"] = stt["model"]
    if stt.get("language"):
        settings["stt_language"] = stt["language"]
    if hot.get("speak"):
        settings["hotkey_speak"] = hot["speak"]
    if hot.get("dictate"):
        settings["hotkey_dictate"] = hot["dictate"]
    with _conn() as c:
        c.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",
                      settings.items())
        for w in cfg.get("vocabulary", {}).get("hints", []):
            c.execute("INSERT OR IGNORE INTO words(word) VALUES (?)", (w,))
        for wrong, right in cfg.get("replacements", {}).items():
            c.execute("INSERT INTO replacements(wrong, right) VALUES (?,?)",
                      (wrong, right))
        for trig, exp in cfg.get("snippets", {}).items():
            c.execute("INSERT INTO snippets(trigger, expansion) VALUES (?,?)",
                      (trig, exp))


# ---------------------------------------------------------------- settings

def get(key: str) -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))


def all_settings() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    out = dict(DEFAULTS)
    out.update({r["key"]: r["value"] for r in rows})
    return out


# ---------------------------------------------------------------- dictionary

def words_list() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM words ORDER BY word")]


def words_add(word: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO words(word) VALUES (?)", (word.strip(),))


def words_delete(wid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM words WHERE id=?", (wid,))


def replacements_list() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM replacements ORDER BY wrong")]


def replacements_add(wrong: str, right: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO replacements(wrong, right) VALUES (?,?)",
                  (wrong.strip(), right.strip()))


def replacements_delete(rid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM replacements WHERE id=?", (rid,))


# ---------------------------------------------------------------- snippets

def snippets_list() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM snippets ORDER BY trigger")]


def snippets_add(trigger: str, expansion: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO snippets(trigger, expansion) VALUES (?,?)",
                  (trigger.strip(), expansion))


def snippets_update(sid: int, trigger: str, expansion: str, enabled: int) -> None:
    with _conn() as c:
        c.execute("UPDATE snippets SET trigger=?, expansion=?, enabled=? WHERE id=?",
                  (trigger.strip(), expansion, enabled, sid))


def snippets_delete(sid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM snippets WHERE id=?", (sid,))


def snippets_hit(sid: int) -> None:
    with _conn() as c:
        c.execute("UPDATE snippets SET uses = uses + 1 WHERE id=?", (sid,))


# ---------------------------------------------------------------- history

def history_add(kind: str, text: str, duration: float,
                snippet: bool = False, audio_path: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO history(type, ts, text, words, duration, snippet, audio_path)"
            " VALUES (?,?,?,?,?,?,?)",
            (kind, time.time(), text, len(text.split()), duration,
             int(snippet), audio_path))
        return cur.lastrowid


def history_list(q: str = "", kind: str = "", limit: int = 200) -> list[dict]:
    sql, args = "SELECT * FROM history WHERE 1=1", []
    if q:
        sql += " AND text LIKE ?"
        args.append(f"%{q}%")
    if kind in ("dictation", "readback"):
        sql += " AND type=?"
        args.append(kind)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def history_get(hid: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM history WHERE id=?", (hid,)).fetchone()
    return dict(row) if row else None


def history_delete(hid: int) -> None:
    entry = history_get(hid)
    if entry and entry.get("audio_path"):
        Path(entry["audio_path"]).unlink(missing_ok=True)
    with _conn() as c:
        c.execute("DELETE FROM history WHERE id=?", (hid,))


# ---------------------------------------------------------------- stats

def _day(ts: float) -> date:
    return datetime.fromtimestamp(ts).date()


def stats(period: str = "week") -> dict:
    days = {"week": 7, "month": 30, "all": 3650}[period]
    cutoff = time.time() - days * 86400
    typing_wpm = max(1, int(float(get("typing_wpm"))))

    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM history ORDER BY ts")]
        snippet_uses = c.execute(
            "SELECT COALESCE(SUM(uses),0) FROM snippets").fetchone()[0]

    cur = [r for r in rows if r["ts"] >= cutoff]
    dic = [r for r in cur if r["type"] == "dictation"]
    rb = [r for r in cur if r["type"] == "readback"]

    words_dictated = sum(r["words"] for r in dic)
    speak_secs = sum(r["duration"] for r in dic)
    keystrokes = sum(len(r["text"]) for r in dic)
    focus_secs = sum(r["duration"] for r in cur)
    # time saved = what typing those words would have cost, minus speaking time
    saved = max(0.0, words_dictated / typing_wpm * 60 - speak_secs)
    speaking_wpm = round(words_dictated / (speak_secs / 60)) if speak_secs else 0

    # streaks over all history
    active = sorted({_day(r["ts"]) for r in rows})
    streak, longest, run, prev = 0, 0, 0, None
    for d in active:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    today = date.today()
    d, sset = today, set(active)
    if d not in sset:
        d -= timedelta(days=1)
    while d in sset:
        streak += 1
        d -= timedelta(days=1)

    # daily activity for charts (chart window capped at 30 days)
    chart_days = min(days, 30)
    labels, dic_series, rb_series = [], [], []
    for i in range(chart_days - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%b %-d"))
        dic_series.append(sum(1 for r in dic if _day(r["ts"]) == d))
        rb_series.append(sum(1 for r in rb if _day(r["ts"]) == d))

    period_days = min(days, max(1, (today - active[0]).days + 1) if active else 1)
    active_in_period = len({_day(r["ts"]) for r in cur})
    momentum = round(100 * active_in_period / period_days)

    return {
        "streak": streak,
        "longest_streak": longest,
        "active_days": len(active),
        "speaking_wpm": speaking_wpm,
        "typing_wpm": typing_wpm,
        "time_saved_secs": round(saved),
        "momentum": momentum,
        "readback_sessions": len(rb),
        "dictation_sessions": len(dic),
        "words_dictated": words_dictated,
        "keystrokes_saved": keystrokes,
        "snippet_uses": snippet_uses,
        "focus_secs": round(focus_secs),
        "chart": {"labels": labels, "dictation": dic_series, "readback": rb_series},
    }
