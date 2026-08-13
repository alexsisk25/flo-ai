"""Learn vocabulary and style from writing you have already done.

The correction watcher in learning.py is precise but slow: it learns one word
per mistake you bother to fix. Your existing writing is a far richer source and
it is already on disk. Point Flo at a folder of notes, memos or emails and it
harvests the proper nouns and jargon you actually use, so Whisper gets them
right the first time instead of the fifth.

Nothing here talks to a network. It reads plain text on your machine, counts
words, and writes to the same SQLite dictionary the dashboard shows.

Deliberately conservative: it proposes, and by default prints rather than
saves. A dictionary stuffed with junk makes Whisper worse, not better, because
every entry is fed to the model as a hint.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

import store

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".org", ".csv", ".json",
                 ".eml", ".vtt", ".srt"}
# Real business writing lives in Word and PDF, not .txt. .docx is a zip of XML
# and needs no dependency. .pdf does, so it is used only if pypdf happens to be
# installed and is never required.
DOC_SUFFIXES = {".docx", ".pdf"}
READABLE = TEXT_SUFFIXES | DOC_SUFFIXES
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
             ".cache", "Library", ".Trash", "dist", "build"}
MAX_FILES = 2000
MAX_BYTES = 2_000_000        # per file; a huge log is not prose

# A word must look like a name or piece of jargon, not ordinary English.
_INTERNAL_CAPS = re.compile(r"^[A-Z][a-z]+[A-Z][A-Za-z]*$")   # CoStar, HubSpot
_ACRONYM = re.compile(r"^[A-Z]{2,6}s?$")                      # NOI, REIT, LOIs
_PROPER = re.compile(r"^[A-Z][a-z]{2,}$")                     # Yardi, Anthropic
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# Common capitalised words that are not worth teaching Whisper.
_STOP = {
    "The", "This", "That", "There", "Then", "They", "These", "Those", "Their",
    "It", "Its", "If", "In", "Is", "As", "At", "An", "And", "Are", "But", "Be",
    "For", "From", "Have", "Has", "He", "Her", "His", "How", "I", "We", "You",
    "Your", "Our", "My", "Me", "Not", "No", "Now", "Of", "On", "Or", "One",
    "So", "Some", "To", "Was", "Were", "What", "When", "Where", "Which", "Who",
    "Will", "With", "Would", "Can", "Could", "Should", "Do", "Does", "Did",
    "Just", "Let", "Like", "Also", "After", "Before", "All", "Any", "Because",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "Sunday", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December", "Hi", "Hey",
    "Hello", "Thanks", "Thank", "Best", "Regards", "Sent", "Subject", "Re",
    "Fwd", "OK", "PM", "AM", "US", "USA", "PDF", "URL", "HTTP", "HTTPS",
}


def _iter_files(root: Path):
    seen = 0
    for p in sorted(root.rglob("*")):
        if seen >= MAX_FILES:
            return
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in READABLE:
            seen += 1
            yield p


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path: Path) -> str:
    """Pull the visible text out of a .docx. It is a zip containing XML."""
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            root = ET.parse(f).getroot()
    parts = []
    for para in root.iter(f"{_W_NS}p"):
        text = "".join(t.text or "" for t in para.iter(f"{_W_NS}t"))
        if text.strip():
            parts.append(text)
    return "\n".join(parts)


def _read_pdf(path: Path) -> str:
    """Best effort, and only if pypdf is already available. Never a hard dep."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            return ""
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return _read_docx(path)
        if suffix == ".pdf":
            return _read_pdf(path)
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[corpus] skipped {path.name}: {type(e).__name__}: {e}")
        return ""


def candidates(text: str) -> Counter:
    """Count words that look like names or jargon rather than ordinary English."""
    found = Counter()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        words = _TOKEN.findall(sentence)
        for i, w in enumerate(words):
            if w in _STOP or len(w) < 2:
                continue
            if _INTERNAL_CAPS.match(w) or _ACRONYM.match(w):
                found[w] += 1                       # distinctive anywhere
            elif _PROPER.match(w) and i > 0:
                found[w] += 1                       # capitalised mid-sentence
    return found


def scan(folder: str, min_count: int = 3, limit: int = 200) -> list[tuple[str, int]]:
    """Return [(word, count)] worth adding, most frequent first."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a folder")
    totals = Counter()
    files = 0
    for path in _iter_files(root):
        files += 1
        totals.update(candidates(_read(path)))
    print(f"[corpus] read {files} file(s) under {root}")
    if not files:
        print("[corpus] nothing readable here. Looked for: "
              + ", ".join(sorted(READABLE)))
    known = {w["word"].lower() for w in store.words_list()}
    ranked = [(w, n) for w, n in totals.most_common()
              if n >= min_count and w.lower() not in known]
    return ranked[:limit]


def apply(words: list[str]) -> int:
    for w in words:
        store.words_add(w)
    return len(words)
