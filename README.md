<div align="center">

<img src="static/apple-touch-icon.png" width="96" alt="Flo">

# Flo

**Talk to your Mac. It types. Select anything. It reads.**

Local voice dictation and narration for macOS — the whole loop, on your own
machine. No cloud, no API keys, no account, no subscription.

Hold **Right Option** to dictate into any app · **Option + S** to hear any selection read aloud

<sub>MIT licensed · Apple Silicon & Intel · Python 3.12+ · ~1.6 GB model, downloaded once</sub>

</div>

<br>

<div align="center">
  <img src="docs/dashboard.png" width="880" alt="The Flo dashboard">
</div>

<br>

---

## Credit

Flo is a fork of **[walnut](https://github.com/Bjepp77/walnut)** by
**[Brandon Jeppson](https://github.com/Bjepp77)**, who wrote the original
local dictation and narration engine, the dashboard, the installer and the test
suite. This fork rebrands it as Flo and adds the local AI cleanup layer, the
learning loop, corpus-seeded vocabulary, and a set of fixes to the macOS
permission, silence-detection and hotkey handling. MIT licensed, then and now.

## Why

Commercial dictation tools are excellent and they all ship your voice somewhere
else. Flo does the same job with Whisper running on your own silicon. Your
audio never leaves the machine, there is nothing to sign up for, and the whole
thing is about 2,600 lines of Python you can read in an afternoon.

It also reads back. Select a paragraph in any app, press `⌥S`, and macOS's own
speech engine narrates it. Two hotkeys, one loop: **your words in, your words
out.**

## Install

```sh
git clone https://github.com/alexsisk25/flo-ai.git
cd flo-ai
./install.sh --app --login
```

That installs [uv](https://docs.astral.sh/uv/) if you need it, resolves
dependencies, runs a self-test, builds `Flo.app`, and starts Flo at login.
Every flag is optional — bare `./install.sh` just sets up the code.

| Flag | Adds |
|:--|:--|
| *(none)* | dependencies + self-test. Run it with `uv run flo.py`. |
| `--app` | `Flo.app` in /Applications — double-click, Spotlight, Launchpad. |
| `--login` | starts Flo automatically at login. |
| `--uninstall` | removes the app and the login item. Your data stays. |

The Flo icon appears in the menu bar. The dashboard lives at
**http://127.0.0.1:8765**.

> **First run downloads the speech model** — about 1.6 GB on Apple Silicon,
> 460 MB on Intel. Once, ever. The dashboard shows a banner while it works.

### Grant two permissions

macOS requires **Accessibility** for global hotkeys and for typing into other
apps. Flo cannot grant it for you, and the confusing part is that macOS grants
it to *the program that runs the code*, not to something called "Flo". So there
are two entries, not one:

> System Settings → Privacy & Security → Accessibility
>
> 1. **Terminal.app** — for running `uv run flo.py` by hand. Quit Terminal with
>    `⌘Q` and reopen it afterwards; the permission is only read at process start,
>    so a new tab is not enough.
> 2. **the `uv` binary** — for the login agent. Run `which uv` (usually
>    `/opt/homebrew/bin/uv`), then click `+`, press `⌘⇧G`, and paste that path.

Without it the hotkeys register and silently never fire — so Flo checks, and
tells you, in the menu bar and on the dashboard. It will not pretend to work.

> **`brew upgrade uv` replaces that binary and can silently void the grant.** If
> the hotkey ever stops firing for no apparent reason, re-add it here first.

**Microphone** is prompted the first time the menu-bar app starts. Click Allow.
If you are never asked, check that `pyobjc-framework-avfoundation` is installed:
without it Flo cannot ask, macOS never prompts, and the mic returns pure silence
while everything *looks* like it is working. Whisper then hallucinates words out
of that silence. This shipped as a real bug and cost weeks to find.

Run `uv run flo.py --doctor` at any time. It reports both permissions and exits
non-zero if either is wrong.

## It fits itself to your Mac

You configure nothing. Flo detects the chip, picks the engine, and picks a
model that is genuinely pleasant on that hardware.

| Your Mac | Engine | Runs on | Default model | Status |
|:--|:--|:--|:--|:--|
| Apple Silicon (M1–M5) | `mlx-whisper` | GPU (Metal) | `large-v3-turbo` | tested |
| Intel | `faster-whisper` | CPU, int8 | `small.en` | **implemented, unverified** |

Flo stores one canonical model name and translates it per engine, so the same
`flo.db` works if you carry it between an Intel and an M-series Mac.

> **Intel Macs:** the code path exists and its dependencies resolve, but Flo
> has never actually been run on Intel silicon. If that's you, you're the first
> — please open an issue with whatever breaks. Everything else here is tested.

## The hotkeys

| Hotkey | What happens |
|:--|:--|
| **Hold Right Option** | Push-to-talk. Chime. Hold and speak. Release. Your words are typed into the frontmost app. |
| **Option + S** | Whatever text you have selected, anywhere, is read aloud. Press again to stop. |
| `⌃⌥C` | Chime. Speak. Chime. The phrase goes to the MegaMind Console instead of being typed (see Voice commands below). **Dormant** — needs a Console you don't have yet; harmless if pressed. |

Dictation is **push-to-talk** (hold the key while speaking), not a toggle, and it
is fixed to the **Right Option** key. Narration is bound to `<alt>+s`, which means
**either** Option key — left or right. Narration and the console command are
re-bindable on the **Shortcuts** page.

## It writes, it doesn't just transcribe

Raw dictation reads like dictation. You say *"um so we should uh meet tuesday
actually make that friday"* and a transcriber faithfully gives you exactly that.
Flo runs the transcript through a small instruction-tuned model
(`Qwen2.5-3B-Instruct-4bit`) on your own GPU before typing it:

| You say | Flo types |
|:--|:--|
| um so we should uh meet tuesday actually make that friday | We should meet on Friday. |
| let's meet Tuesday, I mean Wednesday at the office | Let's meet Wednesday at the office. |
| the deal was around two point one no wait two point four cap rate you know | The deal was around a 2.4 cap rate. |

It fixes grammar and punctuation, strips filler, resolves self-corrections so
the reader can't tell you changed your mind, and writes spoken numbers as
digits. It does **not** summarise, embellish, or answer you — it only cleans
the words that are there.

This costs nothing. It is a local model on your own silicon, not an API call.
It downloads once (~1.7 GB) and everything **fails safe**: if the model isn't
ready or anything throws, you get the raw transcript rather than nothing.

Turn it off in **Settings** if you want strict verbatim capture.

## It learns how you write

Flo watches the field for eight seconds after it types. If you fix something,
it diffs your edit and learns:

- **a corrected spelling** → added to your Dictionary, so Whisper gets it right
  next time. Fix `comms` to `comps` once and it sticks.
- **a recurring word swap or a phrase you always cut** → recorded as a
  preference and fed into the cleanup model's prompt on every future dictation,
  so the output drifts toward how *you* write rather than toward generic
  clean English.

Two deliberate constraints. It only learns from text that has stopped changing,
so typing a correction letter by letter doesn't teach it the half-finished
states. And a single edit becomes a spelling entry only if it *looks* like a
spelling fix; swapping in a genuinely different word is treated as a style
preference, which needs to recur before it counts.

> **Electron apps need a nudge.** Chromium keeps its accessibility tree switched
> off until an assistive client asks for it, so the learning loop appears to work
> only in native apps. Flo sets the private `AXManualAccessibility` attribute on
> the owning process and retries, which wakes it up. Verified working in the
> Claude desktop app.

## Make the narration sound human

**Do this. It takes two minutes and it is the single biggest improvement
available.**

Every Mac defaults to a formant synthesiser from the mid-2000s — the robot you
are picturing. macOS also ships modern neural voices, free and fully offline,
but does not install them and buries the download three levels deep. Most people
never find out they exist.

> System Settings → Accessibility → **Read & Speak** → System voice → Manage Voices
>
> *(on macOS 15 and earlier the pane is called **Spoken Content**)*

Download anything marked **(Premium)** or **(Enhanced)** — Ava, Zoe, Evan, Lee.
Then pick it in Flo's **Settings**, where they're grouped at the top under
*High quality — neural*.

Flo checks for this on every launch. If you have no good voice installed it
says so and offers to open the pane. If you have one but haven't selected it, it
names it. If the voice you picked is later uninstalled — `say` substitutes the
default *silently* — Flo notices that too. It will not pretend to sound good.

Siri's voices are walled off from the `say` command entirely and cannot be used
by any app; Premium is the ceiling. Flo deliberately ships no bundled neural
TTS: every open phonemiser in reach (`espeak-ng`, `phonemizer-fork`, and so
`piper-tts` and `kokoro-onnx`) is GPL-3, which would silently relicense this
MIT project.

## Voice commands (MegaMind Console)

Flo can trigger headless skill runs on the MegaMind Console
(`Claude_Cowork/Projects/console`, must be running — `npm start` there, or
its launchd agent). Trigger + confirm only; no conversations.

End-to-end demo: press `⌃⌥C`, say **"vet this https://github.com/x/y"**,
press `⌃⌥C` again. Flo sends the raw phrase to the Console's `/api/run`,
which matches it against the command-center trigger phrases and starts the
run. Flo says "Running vet skill.", follows the run's stream, and when it
finishes speaks the one-line TL;DR of the result.

- **Ambiguous phrase** (matches two triggers, e.g. "email brief"): Flo
  speaks the top two candidates and asks you to press the hotkey and say
  which one. It never guesses.
- **No match**: Flo says "This needs a real session" — open a terminal or
  Cowork for anything conversational.
- **Console not running**: Flo tells you so.

Settings live in the store like everything else: `hotkey_command` (default
`<ctrl>+<alt>+c`) and `console_url` (default `http://127.0.0.1:4173`), both
changeable via `PUT /api/settings` on the dashboard API.

## The dashboard

<table>
<tr><td width="150"><b>Dashboard</b></td><td>Streak, speaking vs typing WPM, time saved, words dictated, keystrokes you didn't type, activity charts.</td></tr>
<tr><td><b>Dictionary</b></td><td>Words Whisper should know — names, acronyms, jargon — plus fix-ups like <code>"hub spot"</code> → <code>HubSpot</code>. Hints are fed to the model, which rescues proper nouns on the smaller ones.</td></tr>
<tr><td><b>Snippets</b></td><td>Say a phrase, Flo types the expansion. Your email, your sign-off, that URL you can never remember.</td></tr>
<tr><td><b>History</b></td><td>Every session: search, copy, replay the original audio, reveal in Finder, delete.</td></tr>
<tr><td><b>Settings</b></td><td>Voice, speed, language, typing WPM, engine, model — annotated with what your Mac chose and which models will be slow on it.</td></tr>
</table>

Flo ships blank. No sample vocabulary, no snippets — make it yours.

## Choosing a model

Sizes are the download. All of them run entirely on your machine.

| Model | Size | Notes |
|:--|:--|:--|
| `large-v3-turbo` | 1.6 GB | Best accuracy, multilingual. Superb on Apple Silicon, slow on Intel. |
| `medium.en` | 1.5 GB | Very accurate English. Heavy on Intel. |
| `small.en` | 460 MB | The sweet spot on Intel. |
| `base.en` | 140 MB | Fastest. Fumbles names — lean on the Dictionary. |
| `small` / `base` | 460 / 140 MB | Multilingual equivalents. |

Models are cached by Hugging Face under `~/.cache/huggingface`. You can pin the
engine on the Settings page if you want to force `faster-whisper` on Apple
Silicon — useful for comparing.

## Privacy

Everything is local. There is no server, no telemetry, and no account.

- Transcripts and settings live in `flo.db` (SQLite), next to the code.
- Dictation audio lives in `recordings/` — capped at the **newest 3 clips** by
  default, configurable, `0` to keep none.
- The dashboard binds `127.0.0.1` only, and refuses any request whose `Host`
  isn't loopback, so a web page you visit can't reach it.
- The only network calls Flo ever makes are the one-time model downloads from
  Hugging Face: Whisper (~1.6 GB) and, if cleanup is on, Qwen2.5-3B (~1.7 GB).
  After that it never touches the network again. No LLM API is ever called —
  the cleanup model runs on your own GPU, so it costs nothing to run.

## When something breaks

```sh
uv run flo.py --doctor    # chip, engine, model, permissions, paths, log
uv run flo.py --test      # end-to-end check, no mic needed
uv run flo.py --version
```

`--doctor` is the first thing to run and the first thing to paste into an issue.
It exits non-zero if Accessibility is missing.

Hotkeys doing nothing is almost always Accessibility — granted to the wrong
binary, or not at all. Whatever launches Flo is what needs the permission:
your terminal if you run it by hand, `uv` at login, `Flo.app` if you
double-click it. Granting all three is fine.

Logs go to `/tmp/flo.log` when Flo starts at login.

## Development

```sh
uv run --group dev pytest -q     # 96 tests
```

Every test in `tests/` is a bug Flo actually shipped: a dictionary fix-up
containing a backslash that silently killed all dictation, a hotkey that
crash-looped the app, leaked SQLite handles, a prune that deleted the recording
it was in the middle of saving. If one fails, it is telling you the truth.

`tests/test_first_run.py` forces the state a stranger's Mac is in — permission
denied, empty database, model still downloading. Two crash-loop bugs shipped
because nothing ever did that.

```
flo.py    entry point, --test, --doctor    core.py         dictation, narration, hotkeys
stt.py       engine + model selection         store.py        SQLite: settings, history, stats
cleanup.py   local LLM transcript cleanup     learning.py     learns from your corrections
permissions.py  macOS Accessibility + mic     server.py       Flask API
app.py       menu bar app (rumps)             overlay.py      the floating recording pill
install.sh   installer                        static/index.html  the dashboard
console_bridge.py   voice commands → MegaMind Console (dormant, inherited)
```

`config.toml` is read once, on first run, to seed the database. After that the
dashboard is the source of truth. Delete `flo.db` to start over.

## Requirements

macOS — Flo uses the built-in `say` and `afplay`. Python 3.12 or 3.13, which
`uv` handles for you.

## License

[MIT](LICENSE). Take it, change it, ship it.

<div align="center"><sub>❦</sub></div>
