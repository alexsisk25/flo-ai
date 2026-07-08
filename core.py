"""Walnut core: narration, dictation, vocabulary, and global hotkeys.

All settings/vocabulary are read from the SQLite store at time of use, so
edits made in the web UI apply immediately — no restart needed (except for
hotkey changes, which reload the listener via HotkeyManager.reload()).
"""

import re
import subprocess
import threading
import time

import numpy as np

import store

SAMPLE_RATE = 16_000

SOUND_START = "/System/Library/Sounds/Tink.aiff"
SOUND_STOP = "/System/Library/Sounds/Pop.aiff"
SOUND_ERROR = "/System/Library/Sounds/Basso.aiff"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def play_sound(path: str) -> None:
    subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def get_clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def set_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


# --------------------------------------------------------------- whisper
# faster-whisper (CTranslate2, CPU) replaces mlx-whisper so Walnut runs on
# Intel Macs too. Legacy MLX repo names in an existing walnut.db still work.

_MODEL_ALIASES = {
    "mlx-community/whisper-large-v3-turbo": "large-v3-turbo",
    "mlx-community/whisper-small-mlx": "small",
    "mlx-community/whisper-base-mlx": "base",
}
_whisper_cache: dict = {"name": None, "model": None}


def _whisper_model(name: str):
    from faster_whisper import WhisperModel

    name = _MODEL_ALIASES.get(name, name)
    if _whisper_cache["name"] != name:
        _whisper_cache["model"] = WhisperModel(name, device="cpu",
                                               compute_type="int8")
        _whisper_cache["name"] = name
    return _whisper_cache["model"]


def transcribe(audio: np.ndarray, model: str,
               language: str | None = None,
               initial_prompt: str | None = None) -> str:
    segments, _ = _whisper_model(model).transcribe(
        audio, language=language or None, initial_prompt=initial_prompt)
    return "".join(s.text for s in segments).strip()


class Vocabulary:
    """Live view over the store's dictionary/snippets."""

    @staticmethod
    def initial_prompt() -> str | None:
        hints = [w["word"] for w in store.words_list()]
        return ("Vocabulary: " + ", ".join(hints) + ".") if hints else None

    @staticmethod
    def apply(text: str) -> tuple[str, bool]:
        """Returns (processed_text, snippet_used)."""
        if store.get("snippets_enabled") == "1":
            norm = _normalize(text)
            for s in store.snippets_list():
                if s["enabled"] and norm == _normalize(s["trigger"]):
                    store.snippets_hit(s["id"])
                    return s["expansion"], True
        for r in store.replacements_list():
            text = re.sub(re.escape(r["wrong"]), r["right"], text,
                          flags=re.IGNORECASE)
        return text, False


class Core:
    def __init__(self):
        from pynput import keyboard

        self.kb = keyboard.Controller()
        self.say_proc: subprocess.Popen | None = None
        self.stream = None
        self.frames: list[np.ndarray] = []
        self.lock = threading.Lock()
        self.on_state = lambda state: None  # 'idle' | 'recording' | 'busy'
        self.on_level = lambda rms: None    # mic level while recording

    # ------------------------------------------------------------ narration

    def speaking(self) -> bool:
        return self.say_proc is not None and self.say_proc.poll() is None

    def stop_speech(self) -> None:
        if self.speaking():
            self.say_proc.terminate()
        self.say_proc = None

    def _copy_selection(self) -> str:
        from pynput.keyboard import Key

        saved = get_clipboard()
        set_clipboard("")
        time.sleep(0.30)  # let hotkey modifiers be released
        with self.kb.pressed(Key.cmd):
            self.kb.press("c")
            self.kb.release("c")
        time.sleep(0.30)
        selection = get_clipboard()
        set_clipboard(saved)
        return selection

    def speak(self, text: str, record_history: bool = True) -> None:
        self.stop_speech()
        rate = int(float(store.get("tts_rate")))
        voice = store.get("tts_voice")
        cmd = ["say", "-r", str(rate)] + (["-v", voice] if voice else [])
        self.say_proc = subprocess.Popen(cmd + ["-f", "-"],
                                         stdin=subprocess.PIPE)
        self.say_proc.stdin.write(text.encode())
        self.say_proc.stdin.close()
        if record_history:
            est = len(text.split()) / max(rate, 1) * 60
            store.history_add("readback", text, est)

    def toggle_speak(self) -> None:
        if self.speaking():
            self.stop_speech()
            log("Narration stopped.")
            return
        text = self._copy_selection().strip()
        if not text:
            log("No text selected.")
            play_sound(SOUND_ERROR)
            return
        log(f"Narrating {len(text.split())} words…")
        self.speak(text)

    # ------------------------------------------------------------ dictation

    def recording(self) -> bool:
        return self.stream is not None

    def warm_up(self) -> None:
        model = store.get("stt_model")
        log(f"Loading speech model {model}…")
        transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), model)
        log("Speech model ready.")

    def toggle_dictate(self) -> None:
        with self.lock:
            if self.recording():
                self._stop_and_type()
            else:
                self._start_recording()

    def _start_recording(self) -> None:
        import sounddevice as sd

        self.stop_speech()
        self.frames = []

        def on_audio(indata, *_):
            self.frames.append(indata.copy())
            try:
                self.on_level(float(np.sqrt(np.mean(indata ** 2))))
            except Exception:
                pass

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=on_audio,
        )
        self.stream.start()
        play_sound(SOUND_START)
        self.on_state("recording")
        log("Recording…")

    def _stop_and_type(self) -> None:
        self.stream.stop()
        self.stream.close()
        self.stream = None
        play_sound(SOUND_STOP)
        self.on_state("busy")
        try:
            if not self.frames:
                log("No audio captured.")
                return
            audio = np.concatenate(self.frames)[:, 0]
            secs = len(audio) / SAMPLE_RATE
            if secs < 0.4:
                log("Recording too short, ignored.")
                return
            log(f"Transcribing {secs:.1f}s…")
            t0 = time.time()
            text = transcribe(
                audio,
                store.get("stt_model"),
                language=store.get("stt_language") or None,
                initial_prompt=Vocabulary.initial_prompt(),
            )
            text, used_snippet = Vocabulary.apply(text)
            log(f"({time.time() - t0:.1f}s) → {text!r}")
            if not text:
                return
            audio_path = self._save_audio(audio)
            store.history_add("dictation", text, secs,
                              snippet=used_snippet, audio_path=audio_path)
            self._type(text + " ")
        finally:
            self.on_state("idle")

    @staticmethod
    def _save_audio(audio: np.ndarray) -> str:
        import soundfile as sf

        path = store.RECORDINGS / f"dictation-{int(time.time())}.wav"
        sf.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
        return str(path)

    def _type(self, text: str) -> None:
        from pynput.keyboard import Key

        saved = get_clipboard()
        set_clipboard(text)
        time.sleep(0.15)
        with self.kb.pressed(Key.cmd):
            self.kb.press("v")
            self.kb.release("v")
        time.sleep(0.30)
        set_clipboard(saved)


class HotkeyManager:
    """Owns the pynput GlobalHotKeys listener; can reload after key changes."""

    def __init__(self, core: Core):
        self.core = core
        self.listener = None

    def start(self) -> None:
        from pynput import keyboard

        self.stop()
        speak = store.get("hotkey_speak")
        dictate = store.get("hotkey_dictate")

        def on_speak():
            threading.Thread(target=self.core.toggle_speak, daemon=True).start()

        def on_dictate():
            threading.Thread(target=self.core.toggle_dictate, daemon=True).start()

        self.listener = keyboard.GlobalHotKeys({speak: on_speak,
                                                dictate: on_dictate})
        self.listener.start()
        log(f"Hotkeys active: {speak} (narrate), {dictate} (dictate)")

    def stop(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener = None

    def reload(self) -> None:
        self.start()
