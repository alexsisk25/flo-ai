"""Local LLM cleanup — turn a raw voice transcript into clean written text.

Runs a small instruction-tuned model on the Apple Silicon GPU via MLX. Free,
on-device, no network beyond the one-time model download. This is what makes Flo
an AI writing layer rather than plain talk-to-text: it fixes grammar and
punctuation, strips filler words, and resolves spoken self-corrections.

Everything here fails SAFE: if the model isn't ready or anything raises, the raw
transcript is returned unchanged so dictation never breaks.
"""

import re
import threading
import time

import store

DEFAULT_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"

_model = None
_tokenizer = None
_lock = threading.Lock()
_state = "idle"   # 'idle' | 'loading' | 'ready' | 'error'
_error = None


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] cleanup: {msg}", flush=True)


def state() -> str:
    return _state


def error() -> str | None:
    return _error


def enabled() -> bool:
    return store.get("cleanup_enabled") == "1"


def model_name() -> str:
    return store.get("cleanup_model") or DEFAULT_MODEL


def warm_up() -> None:
    """Load the cleanup model (downloads on first run, ~1.7 GB). Called from a
    background thread at startup so dictation works immediately; until it's ready,
    `clean()` returns the raw transcript."""
    global _model, _tokenizer, _state, _error
    if not enabled():
        return
    with _lock:
        if _model is not None or _state == "loading":
            return
        _state = "loading"
    name = model_name()
    log(f"loading cleanup model {name}… (first run downloads it)")
    try:
        from mlx_lm import load
        m, t = load(name)
        with _lock:
            _model, _tokenizer, _state, _error = m, t, "ready", None
        log("cleanup model ready.")
    except Exception as e:
        with _lock:
            _state, _error = "error", f"{type(e).__name__}: {e}"
        log(f"cleanup model failed to load: {_error}")


SYSTEM = (
    "You convert a raw voice transcript into clean written text.\n"
    "Rules:\n"
    "- Fix grammar, punctuation, capitalization, and paragraph breaks.\n"
    "- Remove filler words (um, uh, like, you know).\n"
    "- Resolve self-corrections: if the speaker changes their mind (\"actually\", "
    "\"wait\", \"no\", \"I mean\"), keep only their final intent, and delete the "
    "correction cue word itself. The reader should not be able to tell the speaker "
    "changed their mind.\n"
    "- Write spoken numbers as digits: \"two point four\" -> \"2.4\", \"forty "
    "thousand\" -> \"40,000\", \"twenty twenty six\" -> \"2026\", \"ten percent\" "
    "-> \"10%\". Leave a number alone when it is part of a fixed phrase rather than "
    "a quantity (\"one of the tenants\", \"first thing\").\n"
    "- Do NOT add new content, answer questions, greet, or explain. Only clean and "
    "format the words that are there.\n"
    "- Preserve the speaker's meaning and wording; do not summarize or paraphrase "
    "beyond what the rules require.\n"
    "Output ONLY the cleaned text, with no preamble, quotes, or commentary."
)


# Three worked examples. A 3B model follows a demonstration far more reliably than
# a described rule, and the self-correction case is the one it gets wrong without
# them (it strips the abandoned option but leaves the "actually" behind).
_EXAMPLES = [
    ("um so we should uh meet tuesday actually make that friday",
     "We should meet on Friday."),
    ("i think the number was like forty thousand no sorry fourteen thousand you know",
     "I think the number was 14,000."),
    # The model reliably drops filler at the START of a sentence but tends to strand
    # it at the END once it has spent effort resolving a correction mid-sentence.
    ("i mean the deal was around two point one no wait two point four cap rate you know",
     "The deal was around a 2.4 cap rate."),
]


def _build_system(style, terms, rules) -> str:
    s = SYSTEM
    if style:
        s += f"\n- Apply this writing style: {style}."
    if terms:
        s += "\n- Prefer these known spellings when they appear: " + ", ".join(terms[:40]) + "."
    if rules:
        s += "\n- Apply these learned preferences:\n" + "\n".join(f"  - {r}" for r in rules[:12])
    return s


# Filler the model sometimes strands at the very end of the sentence. Only ever
# applied at the tail, and only to markers that carry no meaning anywhere, so this
# can't eat real words the way a global "like" filter would.
_TRAILING_FILLER = re.compile(
    r"[,;\s]*\b(you know|i mean|um+|uh+)\b\s*([.!?]*)\s*$",
    re.IGNORECASE,
)


_PREAMBLE = re.compile(
    r"^\s*(here'?s|here is|sure|okay|certainly|cleaned( up)? text|output)\b[^\n:]*:\s*",
    re.IGNORECASE,
)


def _postprocess(out: str, fallback: str) -> str:
    out = out.strip()
    if not out:
        return fallback
    # Small models sometimes wrap the answer in quotes or add a lead-in.
    out = _PREAMBLE.sub("", out).strip()
    if len(out) >= 2 and out[0] in "\"'“" and out[-1] in "\"'”":
        out = out[1:-1].strip()
    for _ in range(3):   # markers can stack: "... cap rate, you know, I mean."
        stripped = _TRAILING_FILLER.sub(lambda m: m.group(2), out).strip()
        if stripped == out:
            break
        out = stripped
    if out and out[-1] not in ".!?":
        out += "."
    return out or fallback


def clean(text: str, *, style: str | None = None,
          terms: list[str] | None = None,
          rules: list[str] | None = None) -> str:
    """Clean a raw transcript. Returns the input unchanged if cleanup is off, the
    model isn't ready, or generation fails."""
    if _state != "ready" or not text.strip():
        return text
    try:
        from mlx_lm import generate
        messages = [{"role": "system", "content": _build_system(style, terms, rules)}]
        for raw, cleaned in _EXAMPLES:
            messages.append({"role": "user", "content": raw})
            messages.append({"role": "assistant", "content": cleaned})
        messages.append({"role": "user", "content": text})
        prompt = _tokenizer.apply_chat_template(messages, add_generation_prompt=True)
        # Budget output to the input size; cleanup output is never much longer.
        budget = max(64, min(700, len(text.split()) * 3 + 48))
        out = generate(_model, _tokenizer, prompt=prompt, max_tokens=budget, verbose=False)
        return _postprocess(out, text)
    except Exception as e:
        log(f"cleanup failed, using raw transcript: {type(e).__name__}: {e}")
        return text
