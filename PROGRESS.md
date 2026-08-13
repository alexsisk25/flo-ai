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

## Status — 2026-08-13: FEATURE COMPLETE, EVERYTHING VERIFIED ON DEVICE
Every feature has now been observed working on the machine, not just in tests.
There is no longer anything in this project that is "built but unproven".

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
  Dictionary automatically (observed: `comms -> comps`). Works in native apps
  AND in Electron apps (verified in the Claude desktop app) — see the Electron
  lesson below.
- Silence gate and degenerate-transcript guard (see "Hard-won lessons").
- Web dashboard at http://127.0.0.1:8765, 96 automated tests, installer.

- **Narration** (Option + S). Verified with the Nathan (Enhanced) voice. Reads
  the current selection; press again to stop. See the Option-key lesson below.
- **The login agent.** Installed and running (`com.flo.app`). Flo starts at
  login, lives in the menu bar, needs no terminal open.
- **Corpus learning** (`--learn-from FOLDER`). Seeds the Dictionary from writing
  you have already done: reads .txt/.md/.docx (and .pdf if pypdf is present),
  proposes names and jargon, saves only with `--apply`.

110 automated tests pass.

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

**Electron apps hide their text until asked.** Chromium keeps its accessibility
tree switched off until an assistive client requests it, so `read_focused_text()`
returned nothing in Claude, Slack, VS Code and Notion, and the learning loop
looked like it only worked in native apps. The fix is to set the private
`AXManualAccessibility` attribute on the owning process and retry (`f13a953`).
Done once per pid; native apps ignore it.

**Option is a text-composition modifier, so Option chords need keycodes.**
Pressing Option+S on macOS does not deliver "s" — it delivers "ß" (verified
live: `char='ß', vk=1`). pynput's `GlobalHotKeys` matches the composed
character, so the `<alt>+s` narrate binding registered without error, logged
"Hotkeys active", and was structurally incapable of ever firing. Narration was
in the README, in the menu bar and in `--doctor` for the whole life of the
project and had never once worked. `<alt>+letter` bindings now route to the raw
listener and match on virtual keycode (`_MAC_VK` in core.py). Combos with other
modifiers are fine, because Ctrl and Cmd suppress composition. Fixed in `16d1d03`.

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
Nothing is blocking. Flo works. What is left is optional:
1. Delete the bogus `coms` entry from the Dictionary if still present (learned
   from a half-typed correction before that bug was fixed).
2. Seed the Dictionary properly. `--learn-from ~/Documents` found almost
   nothing because Alex's real writing is not stored as files on the Mac. The
   best source would be sent email; a one-time export to a scratch folder,
   scanned with `--learn-from`, then deleted, would keep Flo itself fully local.
3. Style preferences are learned but only from explicit corrections. Deriving
   them from an existing corpus is designed but not built.
4. Consider widening the learning window; 8s is tight for edits you notice late.

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
