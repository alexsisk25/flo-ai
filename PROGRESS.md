# Flo — Project Ledger

Resume file for any fresh Claude session (Cowork or otherwise). Read this alone and
you can pick up where the last session left off.

## What Flo is
A privacy-first, 100% local voice dictation + narration app for Apple Silicon Macs.
Hold **Right Option** to dictate into any app; **Right Option + S** to read the
selection aloud. Whisper runs on the GPU; there is no cloud, no API keys, no
subscription, and running it costs $0 (no Claude/LLM API calls).

**Provenance:** forked from Brandon's `Bjepp77/walnut` (a working, MIT-licensed tool),
then rebranded to Flo and extended. The `origin` remote still points at Brandon's repo
— **it needs its own home** (see "Repo state" below).

## Current status (honest audit — 2026-07-17)
Lifecycle: **MVP built**, not yet verified end-to-end on device, not shipped.

Works today (verified):
- Rebrand to Flo — cursive monochrome + teal palette, all icons + favicon, zero
  "walnut/squirrel" branding left.
- On-device Whisper transcription (mlx/GPU, large-v3-turbo) — proven by `--test`.
- Storage (SQLite): dictionary, snippets, replacements, history, stats.
- Web dashboard (Dashboard, Dictionary, Snippets, History, Shortcuts, Settings) at
  http://127.0.0.1:8765 — serves + CRUD APIs tested.
- Menu-bar app + installer (`Flo.app` in /Applications + login agent) — builds, runs,
  auto-starts. Single-instance flock lock (no more duplicate icons).
- 96 automated tests pass (`uv run --group dev pytest -q`).

Built but NOT yet verified working:
- **Live push-to-talk dictation end-to-end** — never actually run with Flo's code
  (Accessibility is granted via the `uv` entry; the log shows "Hotkeys active").
- **AI cleanup** (grammar/filler/self-corrections) — wired + logic unit-tested, but the
  ~1.7 GB cleanup model has never downloaded/run (sandbox throttled it). Fails safe to
  raw text until ready.
- **Learning loop** (auto-add corrected spellings + style preferences from your edits)
  — pure diff logic tested (11 tests); the real Accessibility-based watcher unobserved.
- Narration via Right Option + S — new binding, not verified firing.

## How to run / test
```sh
cd "/Users/alexsisk/Desktop/Claude Projects/Flo"
uv run flo.py --doctor        # hardware, engine, model, hotkeys, permissions
uv run flo.py --test          # no-mic end-to-end (TTS -> Whisper -> vocab)
uv run flo.py --clean "TEXT"  # test the AI cleanup on sample text (downloads model 1st run)
uv run --group dev pytest -q  # 96 tests
./install.sh --app --login    # build Flo.app + start at login
```
The permanent instance is the **login agent** `com.flo.app` (runs via `uv`, KeepAlive).
Restart it cleanly: `launchctl kickstart -k "gui/$(id -u)/com.flo.app"`.
Do NOT also `uv run flo.py` manually — that's a second instance (the flock lock now
makes it exit, but don't rely on it).

## Hotkeys
- **Hold Right Option** → push-to-talk dictation (hold, speak, release → types).
- **Right Option + S** → narrate the selected text (press again to stop).
- `Ctrl+Alt+C` → dormant "MegaMind Console" voice command (Brandon's; needs a Console
  you don't have — harmless).

## Architecture (file map)
```
flo.py        entry (--test/--doctor/--clean/--version)   core.py     dictation, narration, hotkeys (push-to-talk)
stt.py        engine + model selection                    store.py    SQLite: settings, dictionary, snippets, history, stats, preferences
cleanup.py    local MLX LLM cleanup (grammar/filler)       learning.py correction watcher + preference diff logic
permissions.py macOS Accessibility/mic                     server.py   Flask dashboard API
app.py        menu-bar app (rumps) + single-instance lock  overlay.py  floating recording pill
console_bridge.py  dormant voice-command bridge            install.sh  installer (Flo.app + login agent)
static/index.html  the dashboard (self-contained HTML/CSS/JS)
Scripts/ (from the abandoned Swift attempt — ignore)       tests/  (96 tests)
```
Settings live in `flo.db` after first run (`config.toml` only seeds it once).

## Next steps (in priority order)
1. **Verify the core loop live** — grant Accessibility (already covered via the `uv`
   entry), then hold Right Option in TextEdit and speak. Confirm text appears.
2. **Verify AI cleanup** — `uv run flo.py --clean "um so we should uh meet tuesday
   actually make that friday"`. First run downloads the model (~1.7 GB). Judge quality;
   if the 3B model disappoints, bump `cleanup.DEFAULT_MODEL` or add an optional Claude
   Haiku path (off by default).
3. **Verify learning** — dictate, fix a word Flo typed, check it lands in the Dictionary.
4. Optional: install a Premium neural voice for narration (Settings banner explains).
5. Roadmap ideas: per-app writing styles, streaming injection, a "Learned preferences"
   management view in the dashboard, shared vocabulary with other tools.

## Repo state (important for continuing in Cowork)
- `origin` = `https://github.com/Bjepp77/walnut.git` (Brandon's — you can't push there).
- gh CLI is authed as `alexsisk25`.
- To give Flo its own home: `gh repo create flo --private --source=. --remote=origin
  --push` (this repoints origin to your account and pushes). Confirm private vs public
  first. Until then the project is local-only and fully committed.
