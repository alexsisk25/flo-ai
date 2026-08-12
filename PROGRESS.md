# Flo — Project Ledger

Resume file for any fresh Claude session. Read this alone and you can pick up
where the last session left off.

## What Flo is
A privacy-first, 100% local voice dictation + narration app for Apple Silicon
Macs. Hold **Right Option** to dictate into any app; **Option + S** to read the
selection aloud. Whisper runs on the GPU, a small local LLM cleans the
transcript, and the app learns your vocabulary from your own corrections. No
cloud, no API keys, no subscription, $0 to run.

**Provenance:** forked from Brandon's `Bjepp77/walnut` (MIT), rebranded and
extended.

## Status — 2026-08-12: WORKING END TO END
The core loop is verified live on device for the first time. Dictation,
cleanup, and the learning loop have all been observed working.

Verified working:
- Push-to-talk dictation. Hold Right Option, speak, release, text is pasted
  into the focused app. Confirmed in TextEdit and in the Claude desktop app.
- On-device Whisper (mlx/GPU, large-v3-turbo). 18.9s of audio transcribed and
  cleaned in 3.2s.
- AI cleanup, live in the dictation path. Resolves self-corrections, strips
  filler, writes spoken numbers as digits.
  `"Let's meet Tuesday, I mean Wednesday at the office."` → `"Let's meet
  Wednesday at the office."`
- Learning loop. Correcting a word Flo typed adds the correct spelling to the
  Dictionary automatically (observed: `comms -> comps`).
- Silence gate and degenerate-transcript guard (see "Hard-won lessons").
- Web dashboard at http://127.0.0.1:8765, 96 automated tests, installer.

NOT yet verified:
- **Narration** (Option + S). Never confirmed firing. Needs a Premium/Enhanced
  system voice installed first; the system default is why `--doctor` warns.
- **The login agent.** `./install.sh --app --login` has not been re-run since
  the repo moved, so Flo currently only runs while `uv run flo.py` is open in
  a terminal. This is the last step to it being a real app.

## Hard-won lessons (do not re-learn these)

**The bug that cost a month.** `pyobjc-framework-avfoundation` was never
declared as a dependency. `permissions.request_microphone()` did
`import AVFoundation` inside a bare `except Exception: pass`, so the import
failed silently, macOS was never asked for mic access, PortAudio returned
digital silence, and Whisper hallucinated from it. The app looked like it heard
you and got it catastrophically wrong. Nothing logged. Fixed in `112df41`.

**Silence is not empty.** Whisper always decodes something. Given silence it
produces confident nonsense: the single word "You", or a repetition loop
("Cluster 07212121…", "nuevo nuevo nuevo…" x400) that then takes the cleanup
model ~30s to tidy while every further hotkey press is rejected as busy. Two
guards now: an RMS silence gate before transcription, and a degenerate-output
detector after it.

**Peak is useless for detecting speech.** Measured on this machine over 5s
holds: silent room peak 0.1157 / rms 0.0028; normal speech peak 0.1329 / rms
0.0187. A quiet room produces transients (keys, desk knocks) that peak as high
as speech. Sustained energy is the only reliable signal. `SILENCE_RMS = 0.005`.
Known limit: global RMS is diluted by long pauses. If a "hold, pause, then
speak" pattern gets wrongly rejected, switch to measuring the loudest stretch.

**Never silently swallow an exception.** As of 2026-08-12 there are zero
`except Exception: pass` handlers in this codebase, and it should stay that
way. The 96 tests pass just as happily with a broken environment as a working
one — they cover logic, not the machine.

**macOS grants permission to the binary, not to "Flo".** Accessibility is
needed twice: on **Terminal.app** for manual runs, and on the **`uv` binary**
(`/opt/homebrew/bin/uv`) for the login agent. `brew upgrade uv` replaces that
binary and can silently void the grant — first place to look if the hotkey
ever dies for no reason.

**Do not keep this repo in iCloud Drive.** It lived on the Desktop, iCloud
evicted the files after two weeks idle, and a running app writing SQLite into a
syncing folder is a corruption waiting to happen. Now at `~/Projects/Flo`.

## How to run / test
```sh
cd ~/Projects/Flo
uv run flo.py --doctor        # hardware, engine, model, hotkeys, permissions
uv run flo.py                 # run it (hotkeys live while this is open)
uv run flo.py --test          # no-mic end-to-end
uv run flo.py --clean "TEXT"  # test the AI cleanup on sample text
uv run --group dev pytest -q  # 96 tests
./install.sh --app --login    # build Flo.app + start at login
```
Restart the login agent: `launchctl kickstart -k "gui/$(id -u)/com.flo.app"`.
Never run `uv run flo.py` manually while the login agent is also running.

## Architecture (file map)
```
flo.py        entry (--test/--doctor/--clean/--version)
core.py       dictation, narration, hotkeys, silence gate, degenerate guard
stt.py        engine + model selection
store.py      SQLite: settings, dictionary, snippets, history, stats, preferences
cleanup.py    local MLX LLM cleanup (system prompt + 4 few-shot examples)
learning.py   correction watcher + preference diff logic
permissions.py macOS Accessibility/mic checks (all failures are logged)
server.py     Flask dashboard API
app.py        menu-bar app (rumps) + single-instance lock
overlay.py    floating recording pill (repositions per-show, follows the cursor's screen)
console_bridge.py  dormant voice-command bridge (Brandon's; unused)
static/index.html  the dashboard
tests/        96 tests
```
Settings live in `flo.db` after first run; `config.toml` only seeds it once.

## Next steps
1. `./install.sh --app --login`, then confirm dictation still works with no
   terminal open. Different execution path; depends on the `uv` Accessibility grant.
2. Install a Premium/Enhanced voice, select it in Settings, verify Option + S.
3. Update `README.md` (still describes the pre-verification project and the old
   repo name).
4. Delete the bogus `coms` entry from the Dictionary if still present.

## Known rough edges
- Narrate is bound to `<alt>+s`, which in pynput means EITHER Option key, not
  Right Option as the docs claim.
- `flo.db` holds a stale `hotkey_dictate` = `<ctrl>+<alt>+d` from the Walnut
  era. Appears unused (dictation is a held key) but it is dead config.
- `Ctrl+Alt+C` still triggers Brandon's dormant MegaMind console bridge.
- Ctrl+C at shutdown prints a leaked-semaphore warning from multiprocessing.
  Cosmetic.
- During tests, a pynput listener thread can die with
  `KeyError: 'AXIsProcessTrusted'` — a pyobjc lazy-import race. Harmless in
  tests; could in principle cause a rare "hotkeys dead at startup" bug.

## Repo state
- `origin` = `https://github.com/alexsisk25/flo-ai.git` (yours, private).
- `upstream` = `https://github.com/Bjepp77/walnut.git` (Brandon's; pull only).
- `flo.db` and `flo.db-*` are gitignored. Two WAL files briefly slipped into
  one commit and were untracked in `763f189`.
