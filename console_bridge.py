"""Voice command bridge to the MegaMind Console (Projects/console).

Trigger + confirm only: a transcribed phrase is POSTed raw to the Console's
/api/run, which resolves it against the command-center trigger phrases and
runs the skill headless. We speak a one-line TL;DR when it finishes. On
ambiguity the top two candidates are spoken back as a question -- never
guessed. Anything needing back-and-forth gets a spoken "this needs a real
session".

Standard library only (urllib); no new walnut dependencies.
"""

import json
import threading
import time
import urllib.error
import urllib.request

import store


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _base() -> str:
    return store.get("console_url").rstrip("/")


def handle(phrase: str, speak) -> None:
    """Send `phrase` to the Console; speak progress and the result TL;DR.

    `speak` is a callable(text) -- app.py passes Core.speak without history.
    """
    phrase = phrase.strip().rstrip(".").strip()
    if not phrase:
        speak("I didn't catch a command.")
        return

    req = urllib.request.Request(
        _base() + "/api/run",
        data=json.dumps({"input": phrase}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rec = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            rec = json.load(e)
        except Exception:
            rec = {}
        if e.code == 422:
            cands = rec.get("candidates") or []
            if len(cands) >= 2:
                speak(f"That could be {_say_name(cands[0])} or "
                      f"{_say_name(cands[1])}. Press the command hotkey "
                      "again and say which one.")
            else:
                speak("No trigger matched that. This needs a real session.")
        else:
            speak("The Console refused that run.")
        log(f"Console declined ({e.code}): {rec.get('reason', phrase)!r}")
        return
    except OSError:
        speak("The Console is not running.")
        log("Console unreachable; is `npm start` running in Projects/console?")
        return

    target = rec.get("target") or "that"
    log(f"Console run {rec.get('id')} started: {target}")
    speak(f"Running {_say_name(target)}.")
    threading.Thread(target=_wait_and_report, args=(rec.get("id"), speak),
                     daemon=True).start()


def _wait_and_report(run_id: str | None, speak) -> None:
    """Follow the run's SSE stream until its end event, then speak the TL;DR."""
    if not run_id:
        return
    end = None
    try:
        url = _base() + f"/api/runs/{run_id}/stream"
        with urllib.request.urlopen(url, timeout=600) as resp:
            event = None
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: ") and event == "end":
                    end = json.loads(line[len("data: "):])
                    break
    except OSError as e:
        log(f"Console stream for {run_id} dropped: {e}")
    if not end:
        speak("I lost track of that run. Check the Console.")
        return

    status = end.get("status", "unknown")
    tldr = end.get("tldr") or ""
    log(f"Console run {run_id} ended: {status} {tldr!r}")
    if status == "done":
        speak(f"Done. {tldr}" if tldr else "Done.")
    else:
        detail = end.get("reason") or tldr
        speak(f"The run {status}." + (f" {detail}" if detail else ""))


def _say_name(name: str) -> str:
    """Make a trigger name speakable: 'vet-skill' -> 'vet skill'."""
    return name.replace("-", " ")
