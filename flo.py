#!/usr/bin/env python3
"""Flo — your work, narrated. Local voice dictation and narration for macOS.

Run `uv run flo.py` to start the menu bar app with global hotkeys
and the dashboard at http://127.0.0.1:8765.

  * Narrate hotkey: reads the text you have selected in ANY app aloud.
  * Dictate hotkey: toggle recording; speech is transcribed locally and typed
    into the frontmost app. Flo picks the engine to match your Mac:
    mlx-whisper on the Apple Silicon GPU, faster-whisper on Intel CPUs.
  * Dashboard: stats, dictionary, snippets, history, shortcuts, settings.

No cloud. No tokens. No subscription.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def self_test() -> int:
    """End-to-end check with no mic or hotkeys: TTS renders a phrase to a wav,
    whisper transcribes it back, vocabulary rules are applied.

    The test writes a throwaway rule, so it runs against a *copy* of your
    database. Your real settings are used; your real data is never touched.
    """
    import shutil
    import tempfile

    import soundfile as sf

    import store

    tmp = Path(tempfile.mkdtemp(prefix="flo-selftest-"))
    if store.DB_PATH.exists():
        shutil.copy(store.DB_PATH, tmp / "flo.db")   # keep the user's settings
    store.DB_PATH = tmp / "flo.db"
    store.RECORDINGS = tmp / "recordings"

    # core reads settings through `store`, so import it only after redirection
    from core import SAMPLE_RATE, Vocabulary

    store.init()
    store.replacements_add("hub spot", "HubSpot")
    phrase = "This is a working test. This came from hub spot."
    wav = tmp / "selftest.wav"

    log("TTS check: rendering test phrase with `say`…")
    subprocess.run(["say", "-o", str(wav), "--data-format=LEF32@16000", phrase],
                   check=True)
    audio, sr = sf.read(wav, dtype="float32")
    assert sr == SAMPLE_RATE

    import stt as speech
    info = speech.describe(store.get("stt_backend"))
    log(f"STT check: {info['backend']} on {info['accelerator']}…")
    from core import transcribe

    result = transcribe(
        audio,
        store.get("stt_model"),
        language="en",
        initial_prompt=Vocabulary.initial_prompt(),
    )
    text, _ = Vocabulary.apply(result)
    log(f"Round-trip transcript: {text!r}")
    shutil.rmtree(tmp, ignore_errors=True)

    ok = "working" in text.lower() and "test" in text.lower()
    fixup_ok = "HubSpot" in text
    log(f"Transcription match: {'PASS' if ok else 'FAIL'}")
    log(f"Vocabulary fix-up ('hub spot' → 'HubSpot'): {'PASS' if fixup_ok else 'FAIL'}")
    return 0 if (ok and fixup_ok) else 1


VERSION = "1.1.3"


def doctor() -> int:
    """Print what Flo sees. First thing to run when something is off."""
    import permissions
    import stt as speech
    import store
    import voices

    store.init()
    info = speech.describe(store.get("stt_backend"))
    log(f"Flo:       v{VERSION}")
    log(f"Mac:          {info['chip']} ({info['machine']})")
    log(f"Engine:       {info['backend']} on {info['accelerator']}")
    log(f"Installed:    {', '.join(info['available_backends'])}")
    log(f"Model:        {speech.canonical(store.get('stt_model'))}")
    log(f"Best here:    {info['default_model']}")
    log(f"Hotkeys:      {store.get_valid('hotkey_speak')} (narrate), "
        f"Right Option hold (dictate, push-to-talk)")
    log(f"Recordings:   keeping {store.get_valid('recordings_keep')}, "
        f"in {store.RECORDINGS}")
    log(f"Database:     {store.DB_PATH}")
    logfile = Path.home() / "Library" / "Logs" / "Flo" / "flo.log"
    if logfile.exists():
        size = logfile.stat().st_size
        log(f"Log:          {logfile}  ({size / 1024:.0f} KB)")
    else:
        log(f"Log:          {logfile}  (not created yet)")
        legacy = Path("/tmp/flo.log")
        if legacy.exists():
            log("  → an old log is still at /tmp/flo.log. Re-run "
                "./install.sh --login to move logging somewhere macOS "
                "does not periodically delete.")

    voice = store.get_valid("tts_voice") or "(system default)"
    vstat = voices.status(store.get("tts_voice"), store.get("stt_language"))
    log(f"Voice:        {voice} — {'good' if vstat['ok'] else vstat['reason']}")
    if not vstat["ok"]:
        log(f"  → {vstat['hint']}")
        if vstat["suggestions"]:
            log(f"  → installed and ready: {', '.join(vstat['suggestions'])}")

    trusted = permissions.accessibility_trusted()
    log(f"Accessibility:{' granted' if trusted else ' MISSING'}")
    if not trusted:
        log("  → Hotkeys will register but never fire. System Settings →")
        log("    Privacy & Security → Accessibility. Then restart Flo.")
    mic = permissions.microphone_status()
    log(f"Microphone:   {mic}")
    if mic in ("denied", "restricted"):
        log("  → Flo will record SILENCE and Whisper will hallucinate a word or")
        log("    two from it (usually \"You\"). System Settings → Privacy &")
        log("    Security → Microphone. Then restart Flo.")
    elif mic == "not_requested":
        log("  → macOS has never been asked. Start the menu-bar app once")
        log("    (./install.sh --app, or launchctl kickstart the login agent)")
        log("    to trigger the prompt; --doctor alone never asks.")

    if info["backend"] == speech.FASTER and speech.is_apple_silicon():
        log("NOTE: Apple Silicon is running the CPU engine. Install mlx-whisper "
            "(`uv sync`) or set backend to 'auto' for a big speed-up.")
    return 0 if (trusted and mic in ("granted", "unknown")) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run a no-mic end-to-end self test and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="show hardware, engine, model, permissions, paths")
    parser.add_argument("--clean", metavar="TEXT",
                        help="run the local AI cleanup on TEXT and print it "
                             "(downloads the cleanup model on first use)")
    parser.add_argument("--learn-from", metavar="FOLDER",
                        help="scan a folder of your own writing for names and "
                             "jargon to add to the Dictionary (prints a "
                             "proposal; add --apply to save it)")
    parser.add_argument("--min-count", type=int, default=3, metavar="N",
                        help="with --learn-from, how many times a word must "
                             "appear to be proposed (default 3)")
    parser.add_argument("--apply", action="store_true",
                        help="with --learn-from, actually save the words")
    parser.add_argument("--version", action="version", version=f"Flo {VERSION}")
    args = parser.parse_args()

    if args.doctor:
        return doctor()
    if args.test:
        return self_test()
    if args.learn_from:
        import corpus
        import store
        store.init()
        try:
            found, near = corpus.scan(args.learn_from,
                                      min_count=args.min_count)
        except NotADirectoryError as e:
            log(str(e))
            return 1
        if not found:
            log(f"Nothing appeared at least {args.min_count} times.")
            if near:
                print(f"\nClosest candidates (below the --min-count "
                      f"{args.min_count} cut-off):\n")
                for word, n in near[:40]:
                    print(f"  {n:5d}  {word}")
                print("\nA small folder rarely repeats a term three times. "
                      "Try --min-count 2,\nor point --learn-from at more of "
                      "your writing.")
            else:
                print("\nNo name-like or jargon-like words at all. Either the "
                      "folder has nothing\nreadable in it (.txt .md .docx "
                      ".pdf), or everything distinctive is\nalready in your "
                      "Dictionary.")
            return 0
        print(f"\n{len(found)} candidate word(s), most frequent first:\n")
        for word, n in found:
            print(f"  {n:5d}  {word}")
        if not args.apply:
            print("\nNothing saved. Re-run with --apply to add these to your "
                  "Dictionary,\nor prune the list first — every entry is fed to "
                  "Whisper as a hint, so\njunk in here makes transcription worse, "
                  "not better.")
            return 0
        n = corpus.apply([w for w, _ in found])
        log(f"Added {n} word(s) to the Dictionary.")
        return 0

    if args.clean is not None:
        import store
        import cleanup
        store.init()
        log("loading cleanup model (first run downloads it, ~1.7 GB)…")
        cleanup.warm_up()
        if cleanup.state() != "ready":
            log(f"cleanup model not ready: {cleanup.state()} ({cleanup.error()})")
            return 1
        print("\nRAW  :", args.clean)
        print("CLEAN:", cleanup.clean(args.clean))
        return 0

    from app import FloApp

    FloApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
