# Flo v1.0.1 — The first-run path must actually run

**Status:** shipped (v1.0.1)
**Author:** Brandon Jeppson
**Date:** 2026-07-09
**Supersedes:** v1.0.0, which crash-loops on first launch.

> All nine criteria met. 54 tests. The integration test was validated by
> reintroducing the v1.0.0 bug and confirming it fails — a test that has never
> failed has not been shown to test anything. `v1.0.0` deleted.
>
> The `Overlay` is stubbed in the construction test because it drives AppKit's
> main run loop, which pytest does not have. Everything else — rumps, the menu
> setter, `Core`, `HotkeyManager` — is real. Stated here rather than hidden.

---

## 1. Problem

`v1.0.0` shipped a fix for the modal first-run failure (missing Accessibility
permission). The fix crashes.

```python
self.menu.insert(0, rumps.MenuItem("⚠️  Grant Accessibility Permission", ...))
```

`rumps.Menu` subclasses `OrderedDict`. It has `add`, `insert_before`, and
`insert_after`. It has no `insert`. The call raises `AttributeError` inside
`FloApp.__init__`, the process dies, and launchd's `KeepAlive` respawns it
into an infinite crash loop.

The branch is guarded by `if not accessibility_trusted()`. That is true for
**every user on first launch** and false on the developer's machine, where the
permission was granted long ago.

So: the one code path that only new users take is the one that was never
executed. 41 tests, a self-test, four headless renders, and a cold-clone
install were all green while the app was unusable for anyone new.

## 2. The real problem

This is the second occurrence of one pattern:

| Bug | Only fires for | Caught by |
|---|---|---|
| Unparseable hotkey crash-loops the app | anyone with a bad stored combo | an audit, not a test |
| `menu.insert` crash-loops the app | **every new user** | a review, not a test |

Tests cover the state the developer's machine is in. Nothing forces the state a
stranger's machine is in. Fixing the line without fixing that is theatre.

## 3. Goal

1. First launch works when Accessibility is missing.
2. The first-run state is a **fixture**, not a hope. Any branch only a new user
   reaches is executed by the suite.
3. No remaining `rumps` API call is taken on faith.

## 4. Non-goals

- Intel verification. Still unverified, still disclosed. Needs hardware.
- Notarization, distribution, new features. Nothing new ships in a patch.

## 5. Success criteria

| # | Criterion | Verified by |
|---|---|---|
| 1 | `FloApp` constructs with Accessibility denied | integration test, no mocks of our own code |
| 2 | The warning menu item is present, first, and clickable | test asserts title + callback |
| 3 | With permission granted, no warning item appears | test asserts absence |
| 4 | Every menu callback names a real method | test resolves each handler |
| 5 | No `rumps` API is assumed | each symbol/signature checked against the library |
| 6 | A `first_run` fixture exists and is used | untrusted + empty DB + model loading |
| 7 | `menu.insert` cannot come back | source assertion |
| 8 | Nothing regressed | full suite + `--test` green |
| 9 | `v1.0.0` no longer points at a crash-looping tree | tag deleted; `v1.0.1` cut |

## 6. Scope

**P0.1 — Fix.** Build the menu as a plain `list` and assign it once. `self.menu`
is only ever a list at the point we mutate it; the `rumps.Menu` object is never
touched. Extract `build_menu(trusted, speak, dictate, handlers) -> list` as a
module-level, GUI-free function so it is testable without a menu bar.

**P0.2 — rumps audit.** Confirm, against the installed library: `App.__init__`
kwargs, `MenuItem.__init__` kwargs, `alert()` signature, `icon` as a settable
property, and that the `menu` setter accepts a list containing `None`
separators. Anything unconfirmed gets removed or verified.

**P0.3 — `first_run` fixture.** `accessibility_trusted() -> False`,
`request_accessibility()` neutered (it shows a system modal), an empty database,
`model_state="loading"`. Tests that assert what a stranger sees.

**P0.4 — Integration test.** Construct the real `FloApp` under `first_run`
on a free port. This is the test that would have caught the bug. It must not
mock `rumps`, or it proves nothing.

**P0.5 — Regression guard.** Assert `.menu.insert(` appears nowhere in the
source. Cheap, specific, and it pins the exact mistake.

**P0.6 — Retag.** Delete `v1.0.0`. Cut `v1.0.1`.

## 7. Risks

- **Constructing `FloApp` in a test** starts a Flask thread, a hotkey
  listener, and an `Overlay` that talks to AppKit. If AppKit misbehaves
  headlessly, fall back to testing `build_menu` plus a narrower construction
  test — but say so, rather than quietly weakening the check.
- **`request_accessibility()` shows a modal.** Must be patched in tests or the
  suite hangs waiting for a human.

## 8. Rollout

1. Land P0. Full suite green.
2. Delete `v1.0.0`, tag `v1.0.1`, push.
3. Restart the local agent, confirm it comes up.
4. *Then* send it to two friends.
