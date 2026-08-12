"""The learning loop — how Flo gets smarter the more you use it.

After Flo types, it watches the field for a few seconds. If you edit what it
wrote, it diffs your change and learns:
  - a corrected spelling  -> added to your dictionary (so Whisper gets it next time)
  - a recurring word swap  -> a 'word_swap' preference fed into the cleanup prompt
  - a phrase you always cut -> a 'phrase_cut' preference

The pure diff logic below has no macOS dependencies and is unit-tested. The
CorrectionWatcher reads the focused field via the Accessibility API (best-effort;
some apps expose nothing) and is exercised manually.
"""

import re
import threading
import time

import store

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for",
    "is", "it", "this", "that", "with", "as", "was", "are", "be", "i", "you",
    "he", "she", "we", "they", "my", "your", "our", "so", "if", "no", "yes",
}
_FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for",
    "is", "it", "this", "that", "with", "as", "i", "you", "so",
}
_TOKEN = re.compile(r"[^\W\d_]+(?:['\-][^\W\d_]+)*|\d+", re.UNICODE)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] learning: {msg}", flush=True)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _lcs_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    la = [w.lower() for w in a]
    lb = [w.lower() for w in b]
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if la[i] == lb[j] else max(dp[i + 1][j], dp[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if la[i] == lb[j]:
            pairs.append((i, j)); i += 1; j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _regions(a: list[str], b: list[str]) -> list[tuple[list[str], list[str]]]:
    """Changed (removed, added) runs between matched anchors."""
    out, ai, bi = [], 0, 0
    for ma, mb in _lcs_pairs(a, b):
        rem, add = a[ai:ma], b[bi:mb]
        if rem or add:
            out.append((rem, add))
        ai, bi = ma + 1, mb + 1
    rem, add = a[ai:], b[bi:]
    if rem or add:
        out.append((rem, add))
    return out


def looks_like_spelling(frm: str, to: str) -> bool:
    """Is `to` a corrected spelling of `frm` (vs. an unrelated word choice)?"""
    f, t = frm.lower(), to.lower()
    if f == t or len(t) < 2:
        return False
    if f in _STOPWORDS or t in _STOPWORDS:
        return False
    dist = levenshtein(f, t)
    longest = max(len(f), len(t))
    if dist <= max(1, longest * 2 // 5):
        return True
    return f[:2] == t[:2] and dist <= longest // 2


def _content_word(w: str) -> bool:
    return len(w) >= 2 and w.lower() not in _FUNCTION_WORDS


def corrections(produced: str, edited: str) -> list[tuple[str, str]]:
    """Word-level spelling corrections the user made."""
    a, b = tokenize(produced), tokenize(edited)
    if not a or not b:
        return []
    out = []
    for rem, add in _regions(a, b):
        for i in range(min(len(rem), len(add))):
            if looks_like_spelling(rem[i], add[i]):
                out.append((rem[i], add[i]))
    return out


def preferences(produced: str, edited: str) -> list[tuple[str, str, str]]:
    """Recurring style edits as (kind, from, to). Word swaps that are NOT spelling
    fixes, and short pure deletions (phrases the user cut)."""
    a, b = tokenize(produced), tokenize(edited)
    if not a:
        return []
    out = []
    for rem, add in _regions(a, b):
        sub = min(len(rem), len(add))
        for i in range(sub):
            frm, to = rem[i], add[i]
            if frm.lower() == to.lower():
                continue
            if looks_like_spelling(frm, to):
                continue
            if _content_word(frm) and _content_word(to):
                out.append(("word_swap", frm.lower(), to.lower()))
        if len(add) < len(rem):
            cut = rem[len(add):]
            if 1 <= len(cut) <= 4 and any(_content_word(w) for w in cut):
                out.append(("phrase_cut", " ".join(w.lower() for w in cut), ""))
    return out


# ------------------------------------------------------------ Accessibility read

def read_focused_text() -> str | None:
    """The text of the currently focused UI element, via the Accessibility API.
    Returns None for secure fields or when the app exposes nothing."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
            kAXFocusedUIElementAttribute, kAXValueAttribute, kAXRoleAttribute,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return None
        rerr, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        if role == "AXSecureTextField":
            return None
        verr, value = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if verr != 0 or not isinstance(value, str):
            return None
        return value
    except Exception:
        return None


class CorrectionWatcher:
    """Samples the focused field for a short window after injection and learns
    from any edits. Fails silent; never disturbs dictation."""

    def __init__(self):
        self._timer = None
        self._learned_from = None
        self._last_seen = None
        self._produced = ""

    def enabled(self) -> bool:
        return store.get("learn_enabled") == "1"

    def watch(self, produced_text: str, window: float = 8.0) -> None:
        if not self.enabled():
            return
        self.stop()
        self._produced = produced_text
        start = read_focused_text()
        self._learned_from = start   # last state we have already learned from
        self._last_seen = start      # last state we saw, settled or not
        self._elapsed = 0.0
        self._window = window
        self._tick()

    def _tick(self) -> None:
        self._sample()
        self._elapsed += 1.0
        if self._elapsed < self._window:
            self._timer = threading.Timer(1.0, self._tick)
        else:
            # One last look after the window, so an edit finished right at the
            # boundary still counts.
            self._timer = threading.Timer(1.5, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _sample(self) -> None:
        """Learn only from text that has stopped changing.

        The naive version learned from every poll, which meant typing "comps"
        one letter at a time taught Flo that "coms" was a word. A correction is
        only real once the user has stopped typing it, so require the field to
        look identical on two consecutive samples before committing.
        """
        current = read_focused_text()
        if current is None:
            return
        if current != self._last_seen:
            self._last_seen = current      # still mid-edit; wait for it to settle
            return
        self._commit(current)

    def _flush(self) -> None:
        self._timer = None
        current = read_focused_text()
        if current is not None:
            self._commit(current)

    def _commit(self, current: str) -> None:
        """Diff against the last state we learned from and record what changed."""
        if current == self._learned_from:
            return
        base = (self._learned_from if self._learned_from is not None
                else self._produced)
        try:
            for frm, to in corrections(base, current):
                store.words_add(to)
                log(f"learned spelling: {frm} -> {to}")
            for kind, frm, to in preferences(base, current):
                store.preferences_learn(kind, frm, to)
                log(f"learned preference: {kind} {frm!r} -> {to!r}")
        except Exception as e:
            log(f"sample failed: {type(e).__name__}: {e}")
        self._learned_from = current

    def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
