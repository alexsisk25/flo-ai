# Walnut 🥜

Local voice dictation and narration for macOS — the two-way voice loop,
rebuilt to run **100% locally on your Mac**. No cloud, no tokens, no
subscription. Speech-to-text is `mlx-whisper` on the Apple Silicon GPU;
narration is macOS's built-in `say`.

## Run it

```sh
cd ~/walnut
uv run walnut.py
```

A small squirrel appears in the menu bar (a filled dot joins it while
recording, a hollow dot while transcribing) and the dashboard is served at
**http://127.0.0.1:8765**. Walnut is installed to start at login via
`~/Library/LaunchAgents/com.brandon.walnut.plist`; to stop that, run
`launchctl unload ~/Library/LaunchAgents/com.brandon.walnut.plist`.

## What it does

| Hotkey | Action |
|---|---|
| `⌃⌥S` | Narrate whatever text is selected in ANY app. Press again to stop. |
| `⌃⌥Space` | Toggle dictation: chime → speak → chime, transcript is typed into the frontmost app. |

Hotkeys are configurable on the dashboard's **Shortcuts** page (applies
instantly, no restart).

## The dashboard

- **Dashboard** — streak, speaking vs typing WPM, time saved, session counts,
  words dictated, keystrokes saved, activity charts, performance summary.
- **Dictionary** — words Whisper should recognize (names, acronyms) plus
  fix-ups (auto-corrections like "hub spot" → "HubSpot").
- **Snippets** — say a phrase, Walnut types the expansion ("insert my email"
  → your address). Global on/off, per-snippet enable, use counts, search.
- **History** — every dictation/read-back session: search, filter, copy the
  transcript, **Replay** (dictations replay the actual audio recording),
  **Show in Finder** (recordings live in `recordings/`), delete.
- **Shortcuts / Settings** — hotkeys, narration voice + speed, Whisper model,
  language, and your typing WPM (drives the time-saved math).

All data lives in `walnut.db` (SQLite) on this Mac. UI edits apply live.

## One-time macOS permissions

1. **Accessibility** — System Settings → Privacy & Security → Accessibility →
   add your terminal app. Required for global hotkeys and typing into other
   apps. Restart Walnut after granting.
2. **Microphone** — macOS prompts on first dictation; click Allow.
3. **Input Monitoring** — if hotkeys still don't fire, also add your terminal
   there.

## Tuning

- **Voices**: better ones (Siri / Enhanced / Premium) download in System
  Settings → Accessibility → Spoken Content → System Voice → Manage Voices,
  then pick them on the Settings page.
- **Model**: default `whisper-large-v3-turbo` (~1.6 GB, ≈1 s per sentence on
  an M5). Settings page offers smaller/faster models.

## Self-test (no mic needed)

```sh
uv run walnut.py --test
```

TTS renders a phrase → Whisper transcribes it back → vocabulary fix-ups are
verified. Should print two PASS lines.

## Start at login

Already installed (`~/Library/LaunchAgents/com.brandon.walnut.plist`,
KeepAlive on — it relaunches if it crashes). Logs go to `/tmp/walnut.log`.

```sh
launchctl unload ~/Library/LaunchAgents/com.brandon.walnut.plist  # stop + disable
launchctl load   ~/Library/LaunchAgents/com.brandon.walnut.plist  # re-enable
```

When run via launchd, grant Accessibility/Microphone to
`~/walnut/.venv/bin/python3` if macOS prompts.

## Files

```
walnut.py   entry point + self-test     core.py   narration/dictation/hotkeys
app.py      menu bar app (rumps)        store.py  SQLite (settings/history/…)
server.py   Flask API                   static/index.html  the dashboard UI
walnut.db   your data                   recordings/  dictation audio (wav)
```

`config.toml` is only read once, on first run, to seed the database.
