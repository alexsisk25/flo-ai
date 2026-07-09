#!/usr/bin/env python3
"""Walnut — your work, narrated. Local voice dictation and narration for macOS.

Run `uv run walnut.py` to start the menu bar app (🥜) with global hotkeys
and the dashboard at http://127.0.0.1:8765.

  * Narrate hotkey: reads the text you have selected in ANY app aloud.
  * Dictate hotkey: toggle recording; speech is transcribed locally and typed
    into the frontmost app. Walnut picks the engine to match your Mac:
    mlx-whisper on the Apple Silicon GPU, faster-whisper on Intel CPUs.
  * Dashboard: stats, dictionary, snippets, history, shortcuts, settings.

No cloud. No tokens. No subscription.
"""

import argparse
import subprocess
import sys
import time

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
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="walnut-selftest-"))
    if store.DB_PATH.exists():
        shutil.copy(store.DB_PATH, tmp / "walnut.db")   # keep the user's settings
    store.DB_PATH = tmp / "walnut.db"
    store.RECORDINGS = tmp / "recordings"

    # core reads settings through `store`, so import it only after redirection
    from core import SAMPLE_RATE, Vocabulary

    store.init()
    store.replacements_add("hub spot", "HubSpot")
    phrase = "Walnut is working. This came from hub spot."
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

    ok = "walnut" in text.lower() and "working" in text.lower()
    fixup_ok = "HubSpot" in text
    log(f"Transcription match: {'PASS' if ok else 'FAIL'}")
    log(f"Vocabulary fix-up ('hub spot' → 'HubSpot'): {'PASS' if fixup_ok else 'FAIL'}")
    return 0 if (ok and fixup_ok) else 1


def doctor() -> int:
    """Print what Walnut sees. First thing to run when something is off."""
    import stt as speech
    import store

    store.init()
    info = speech.describe(store.get("stt_backend"))
    log(f"Mac:          {info['chip']} ({info['machine']})")
    log(f"Engine:       {info['backend']} on {info['accelerator']}")
    log(f"Installed:    {', '.join(info['available_backends'])}")
    log(f"Model:        {speech.canonical(store.get('stt_model'))}")
    log(f"Best here:    {info['default_model']}")
    if info["backend"] == speech.FASTER and speech.is_apple_silicon():
        log("NOTE: Apple Silicon is running the CPU engine. Install mlx-whisper "
            "(`uv sync`) or set backend to 'auto' for a big speed-up.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run a no-mic end-to-end self test and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="show detected hardware, engine, and model")
    args = parser.parse_args()

    if args.doctor:
        return doctor()
    if args.test:
        return self_test()

    from app import WalnutApp

    WalnutApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
