#!/usr/bin/env python3
"""Walnut — your work, narrated. Local voice dictation and narration for macOS.

Run `uv run walnut.py` to start the menu bar app (🥜) with global hotkeys
and the dashboard at http://127.0.0.1:8765.

  * Narrate hotkey: reads the text you have selected in ANY app aloud.
  * Dictate hotkey: toggle recording; speech is transcribed locally
    (mlx-whisper on Apple Silicon) and typed into the frontmost app.
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
    whisper transcribes it back, vocabulary rules are applied."""
    import soundfile as sf

    import store
    from core import SAMPLE_RATE, Vocabulary
    from pathlib import Path

    store.init()
    store.replacements_add("hub spot", "HubSpot")
    phrase = "Walnut is working. This came from hub spot."
    wav = Path(__file__).resolve().parent / ".selftest.wav"

    log("TTS check: rendering test phrase with `say`…")
    subprocess.run(["say", "-o", str(wav), "--data-format=LEF32@16000", phrase],
                   check=True)
    audio, sr = sf.read(wav, dtype="float32")
    assert sr == SAMPLE_RATE

    log("STT check: transcribing it back with mlx-whisper…")
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=store.get("stt_model"),
        language="en",
        initial_prompt=Vocabulary.initial_prompt(),
    )
    text, _ = Vocabulary.apply(result["text"].strip())
    log(f"Round-trip transcript: {text!r}")
    wav.unlink(missing_ok=True)

    ok = "walnut" in text.lower() and "working" in text.lower()
    fixup_ok = "HubSpot" in text
    log(f"Transcription match: {'PASS' if ok else 'FAIL'}")
    log(f"Vocabulary fix-up ('hub spot' → 'HubSpot'): {'PASS' if fixup_ok else 'FAIL'}")
    return 0 if (ok and fixup_ok) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run a no-mic end-to-end self test and exit")
    args = parser.parse_args()

    if args.test:
        return self_test()

    from app import WalnutApp

    WalnutApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
