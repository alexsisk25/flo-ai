"""Flask API + static UI for the Walnut dashboard."""

import logging
import re
import subprocess
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import store

HERE = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=str(HERE / "static"))
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# wired up by app.py
CORE = None
HOTKEYS = None


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------- dashboard

@app.route("/api/dashboard")
def dashboard():
    period = request.args.get("period", "week")
    if period not in ("week", "month", "all"):
        period = "week"
    return jsonify(store.stats(period))


# ---------------------------------------------------------------- dictionary

@app.route("/api/words", methods=["GET", "POST"])
def words():
    if request.method == "POST":
        w = (request.json or {}).get("word", "").strip()
        if w:
            store.words_add(w)
    return jsonify(store.words_list())


@app.route("/api/words/<int:wid>", methods=["DELETE"])
def words_delete(wid):
    store.words_delete(wid)
    return jsonify({"ok": True})


@app.route("/api/replacements", methods=["GET", "POST"])
def replacements():
    if request.method == "POST":
        d = request.json or {}
        if d.get("wrong", "").strip() and d.get("right", "").strip():
            store.replacements_add(d["wrong"], d["right"])
    return jsonify(store.replacements_list())


@app.route("/api/replacements/<int:rid>", methods=["DELETE"])
def replacements_delete(rid):
    store.replacements_delete(rid)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- snippets

@app.route("/api/snippets", methods=["GET", "POST"])
def snippets():
    if request.method == "POST":
        d = request.json or {}
        if d.get("trigger", "").strip() and d.get("expansion", "").strip():
            store.snippets_add(d["trigger"], d["expansion"])
    return jsonify({
        "enabled": store.get("snippets_enabled") == "1",
        "snippets": store.snippets_list(),
    })


@app.route("/api/snippets/<int:sid>", methods=["PUT", "DELETE"])
def snippet_item(sid):
    if request.method == "DELETE":
        store.snippets_delete(sid)
    else:
        d = request.json or {}
        store.snippets_update(sid, d["trigger"], d["expansion"],
                              int(d.get("enabled", 1)))
    return jsonify({"ok": True})


@app.route("/api/snippets/toggle", methods=["POST"])
def snippets_toggle():
    now = "0" if store.get("snippets_enabled") == "1" else "1"
    store.set_setting("snippets_enabled", now)
    return jsonify({"enabled": now == "1"})


# ---------------------------------------------------------------- history

@app.route("/api/history")
def history():
    return jsonify(store.history_list(
        q=request.args.get("q", ""),
        kind=request.args.get("type", ""),
        limit=int(request.args.get("limit", 200)),
    ))


@app.route("/api/history/<int:hid>", methods=["DELETE"])
def history_delete(hid):
    store.history_delete(hid)
    return jsonify({"ok": True})


@app.route("/api/history/<int:hid>/replay", methods=["POST"])
def history_replay(hid):
    entry = store.history_get(hid)
    if not entry:
        return jsonify({"error": "not found"}), 404
    audio = entry.get("audio_path")
    if audio and Path(audio).exists():
        subprocess.Popen(["afplay", audio], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    elif CORE:
        threading.Thread(target=CORE.speak, args=(entry["text"], False),
                         daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/history/<int:hid>/reveal", methods=["POST"])
def history_reveal(hid):
    entry = store.history_get(hid)
    audio = entry.get("audio_path") if entry else None
    if audio and Path(audio).exists():
        subprocess.run(["open", "-R", audio])
        return jsonify({"ok": True})
    return jsonify({"error": "no recording for this entry"}), 404


# ---------------------------------------------------------------- settings

@app.route("/api/settings", methods=["GET", "PUT"])
def settings():
    if request.method == "PUT":
        d = request.json or {}
        hotkeys_changed = False
        for key in store.DEFAULTS:
            if key in d:
                if key.startswith("hotkey_") and str(d[key]) != store.get(key):
                    hotkeys_changed = True
                store.set_setting(key, str(d[key]))
        if hotkeys_changed and HOTKEYS:
            HOTKEYS.reload()
    return jsonify(store.all_settings())


@app.route("/api/voices")
def voices():
    out = subprocess.run(["say", "-v", "?"], capture_output=True,
                         text=True).stdout
    result = []
    for line in out.splitlines():
        m = re.match(r"^(.*?)\s{2,}(\S+)\s+#\s*(.*)$", line)
        if m:
            result.append({"name": m.group(1).strip(),
                           "locale": m.group(2), "sample": m.group(3)})
    return jsonify(result)


@app.route("/api/test-voice", methods=["POST"])
def test_voice():
    if CORE:
        d = request.json or {}
        threading.Thread(
            target=CORE.speak,
            args=(d.get("text", "Walnut here. This is how I sound."), False),
            daemon=True).start()
    return jsonify({"ok": True})


def run(port: int) -> None:
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
