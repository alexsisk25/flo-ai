> **Provenance:** this document was written by Brandon Jeppson for
> [walnut](https://github.com/Bjepp77/walnut), the project Flo is forked
> from. It is kept here as history. The product name reads "Flo" because
> the rebrand renamed it; Brandon did not write requirements for Flo.

# Flo v1.0 — Shippable

**Status:** shipped (v1.0.0)
**Author:** Brandon Jeppson
**Date:** 2026-07-09

> All nine success criteria met. P0, P1, and P2 landed. Two defects were found
> by rendering the dashboard — a broken `⟳` glyph and an empty state quoting a
> stale hotkey — neither of which any structural check would have caught.
> Remaining known gap: Intel is still unverified, and is now labelled as such.

---

## 1. Problem

Flo works. It is also, today, unshippable to anyone who did not build it.

The engineering is sound: hardware-adaptive speech backends, a validated
settings layer, a 35-test regression suite. None of that is what a new user
meets. What they meet is the first ten minutes, and the first ten minutes are
where Flo fails.

The defining failure: **macOS requires Accessibility permission for global
hotkeys, and without it `pynput` does not error — it silently never fires.**
Flo prints `Hotkeys active`, shows the Flo icon in the menu bar, and
does nothing when you press the key. The app is not broken. The app is lying.

A friend who hits this has no error, no banner, no log they would know to open.
They close the terminal and never mention it.

## 2. Goal

A person who has never seen this repo can go from `git clone` to a working
dictation in under ten minutes, **and at every moment where it could fail,
Flo tells them exactly what is wrong and how to fix it.**

Robustness is done. This release is about legibility.

## 3. Non-goals

- Notarized `.dmg` distribution. Friends clone the repo. Revisit if strangers ask.
- Windows or Linux. Flo is built on `say`, `afplay`, and AppKit.
- Cloud anything. The product is that nothing leaves the machine.
- A settings UI for every knob. `config.toml` and the dashboard already cover it.

## 4. Success criteria

Flo v1.0 ships when all of the following are true:

| # | Criterion | How it's verified |
|---|---|---|
| 1 | Flo never claims a capability it does not have | `Hotkeys active` is printed only when `AXIsProcessTrusted()` |
| 2 | A user missing Accessibility is told, in the app | menu bar item + dashboard banner + `--doctor` |
| 3 | A user can see the model downloading | menu bar state + dashboard banner |
| 4 | The repo is legally usable | `LICENSE` exists |
| 5 | Default hotkeys collide with nothing | dictate moves off ⌃⌥Space |
| 6 | A human has looked at the dashboard | rendered screenshot, reviewed |
| 7 | Support is one command | `--doctor` reports chip, engine, model, permissions, log path |
| 8 | Claims in the README are true | Intel support labelled as unverified until it isn't |
| 9 | Nothing regressed | `pytest` green, `--test` green |

## 5. Scope

### P0 — blocks sharing the link

**P0.1 Permission truth.** A `permissions.py` exposing `accessibility_trusted()`.
`HotkeyManager.start()` logs the truth. `app.py` grows a menu item that reads
`⚠️ Grant Accessibility Permission` when untrusted and opens the correct System
Settings pane on click. `/api/status` exposes it; the dashboard shows a banner.

*Why first:* it is the modal failure. Every other bug is a distant second.

**P0.2 LICENSE.** MIT. Without it the repo is all-rights-reserved by default and
nobody may legally use it.

**P0.3 Model download visibility.** `Core.model_state` ∈ {`loading`, `ready`,
`error`}. Surfaced in the menu bar, on `/api/status`, and as a dashboard banner.
`install.sh` warns about the ~1.6 GB download *before* it starts.

*Why:* on first launch the app looks installed and inert for several minutes.

**P0.4 Look at it.** Render the dashboard headlessly, screenshot it, review it.
The stylesheet was rewritten wholesale and no human has seen the result.

### P1 — blocks recommending it

**P1.5 Hotkey defaults.** macOS assigns ⌃⌥Space to "Select next source in Input
menu" for anyone with two keyboard layouts. Move dictate to ⌃⌥D. Existing
databases keep their bindings.

**P1.6 Intel honesty.** Flo has never run on Intel silicon. The thread cap
that works around a ctranslate2 segfault has never executed on the platform it
exists for. Until someone runs it there, the README says so.

**P1.7 One-command support.** `--version`. `--doctor` prints permissions and the
log path. When a friend says "it's broken," one command answers it.

### P2 — polish

**P2.8** The `.app` is a thin launcher holding an absolute path; moving the repo
breaks it. Detect and say so.
**P2.9** Dashboard empty state — a first-run prompt instead of a wall of zeros.

## 6. Risks

- **Accessibility cannot be granted programmatically.** We can detect and deep-link;
  the user must click. The prompt API (`AXIsProcessTrustedWithOptions`) shows a
  system dialog once per binary. Acceptable.
- **TCC identity of `Flo.app`** is the ad-hoc-signed bundle, but the executable
  is a shell script. Grant behaviour is untested. Document, don't guess.
- **Intel remains unverified** after this release. Mitigated by labelling, not by
  code.

## 7. Rollout

1. Land P0, tag `v1.0.0`.
2. Send to two friends — one Apple Silicon, one Intel. The Intel friend is told
   they are the first.
3. Fix what they hit. Then it is a product.
