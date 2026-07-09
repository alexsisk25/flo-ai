# Walnut 🥜

A local, free rebuild of commercial voice dictation tools
and Wispr Flow — the two-way voice loop, running **100% on your Mac**.

Talk to any app and Walnut types what you said. Select text anywhere and Walnut
reads it aloud. Nothing leaves the machine: no cloud, no API keys, no tokens,
no subscription.

Walnut fits itself to whatever Mac it lands on:

| Your Mac | Engine | Runs on | Default model |
|---|---|---|---|
| Apple Silicon (M1–M5) | `mlx-whisper` | GPU (Metal) | `large-v3-turbo` |
| Intel | `faster-whisper` | CPU (int8) | `small.en` |

You don't configure this. Walnut detects the chip, picks the engine, and picks
a model that is actually pleasant to use on that hardware — the big model where
the GPU makes it cheap, a small one where transcription lands on the CPU.

## Install

```sh
git clone https://github.com/Bjepp77/walnut.git
cd walnut
./install.sh --app --login
```

That installs [uv](https://docs.astral.sh/uv/) if you don't have it, pulls
dependencies, runs a self-test, builds `Walnut.app`, and starts Walnut at
login. Every flag is optional — bare `./install.sh` just sets up the code.

| Flag | What it adds |
|---|---|
| *(none)* | dependencies + self-test. Run with `uv run walnut.py`. |
| `--app` | `Walnut.app` in /Applications — double-click, Spotlight, Launchpad. |
| `--login` | starts Walnut automatically at login. |
| `--uninstall` | removes the app and the login item. Keeps your data. |

A squirrel appears in the menu bar and the dashboard lives at
**http://127.0.0.1:8765**.

`Walnut.app` is a thin launcher, not a frozen bundle: it runs this repo through
`uv`. Pull new code and the app picks it up — nothing to rebuild. If Walnut is
already running, opening the app just shows the dashboard instead of starting a
second copy.

### macOS permissions (once)

Walnut cannot grant these for you.

1. **Accessibility** — System Settings → Privacy & Security → Accessibility →
   add your terminal. Needed for global hotkeys and typing into other apps.
   **Restart Walnut afterwards.**
2. **Microphone** — macOS prompts on first dictation. Allow.
3. **Input Monitoring** — only if hotkeys still don't fire.

Which binary do you grant? Whatever launches Walnut: your terminal when you run
it by hand, `uv` when it starts at login, `Walnut.app` when you double-click it.
Granting all three is fine.

## Use it

| Hotkey | Action |
|---|---|
| `⌃⌥S` | Narrate the selected text in ANY app. Press again to stop. |
| `⌃⌥Space` | Toggle dictation: chime → speak → chime → transcript is typed. |

Both are re-bindable on the dashboard's **Shortcuts** page, live, no restart.

## The dashboard

- **Dashboard** — streak, speaking vs typing WPM, time saved, words dictated,
  keystrokes saved, activity charts.
- **Dictionary** — words Whisper should know (names, acronyms) and fix-ups
  (`"hub spot"` → `HubSpot`). Dictionary entries are fed to Whisper as hints,
  which genuinely rescues proper nouns on the smaller models.
- **Snippets** — say a phrase, Walnut types the expansion.
- **History** — every session: search, copy, **Replay** (dictations replay the
  original audio; press again to stop), Show in Finder, delete.
- **Settings** — voice, speed, language, typing WPM, and the model/engine
  picker, which shows what your Mac chose and flags models that will be slow
  on it.

All data lives in `walnut.db` (SQLite) next to the code. It never leaves.

## Choosing a model

The Settings page lists these; sizes are the download.

| Model | Size | Notes |
|---|---|---|
| `large-v3-turbo` | 1.6 GB | Best accuracy, multilingual. Great on Apple Silicon, slow on Intel. |
| `medium.en` | 1.5 GB | Very accurate English. Heavy on Intel. |
| `small.en` | 460 MB | The sweet spot on Intel. |
| `base.en` | 140 MB | Fastest. Fumbles names — lean on the Dictionary. |
| `small` / `base` | 460 / 140 MB | Multilingual equivalents. |

Models download on first use and are cached by Hugging Face under
`~/.cache/huggingface`.

Walnut stores one canonical name (`small.en`) and translates it per engine, so
the same `walnut.db` works if you move it between an Intel and an M-series Mac.

You can pin the engine on the Settings page (or `backend` in `config.toml`) if
you want to force `faster-whisper` on Apple Silicon — useful for comparing.

## Troubleshooting

```sh
uv run walnut.py --doctor        # what chip, engine, and model did Walnut find?
uv run walnut.py --test          # end-to-end check, no mic needed. Two PASS lines.
uv run --group dev pytest -q     # the regression suite
```

`--test` runs against a *copy* of your database, so it never touches your data.

Every test in `tests/` is a bug Walnut actually shipped — a fix-up containing a
backslash that killed all dictation, a hotkey that crash-looped the app, leaked
database handles. If you change something and one fails, it is telling you the
truth.

Hotkeys silently doing nothing is almost always Accessibility permission not
granted, or granted to the wrong binary (your terminal when you run Walnut by
hand, `uv` when it starts at login).

## Start at login

```sh
./install.sh --login      # enable
./install.sh --uninstall  # disable (keeps walnut.db and recordings)
```

Logs go to `/tmp/walnut.log`. The agent has `KeepAlive` on, so it relaunches
if it crashes.

Walnut.app is signed ad-hoc, not notarized. That's invisible to you because you
built it locally. If you ever hand someone the built `.app` instead of the repo,
Gatekeeper will block it — send them the repo.

## Files

```
walnut.py   entry point, --test, --doctor   core.py    narration/dictation/hotkeys
stt.py      engine + model selection        store.py   SQLite (settings/history/…)
app.py      menu bar app (rumps)            server.py  Flask API
install.sh  installer                       static/index.html  the dashboard
```

`config.toml` is read once, on first run, to seed the database. After that the
dashboard is the source of truth. Delete `walnut.db` to re-seed.

## Requirements

macOS (uses the built-in `say` and `afplay`), Python 3.12 or 3.13 — `uv`
handles Python for you.
