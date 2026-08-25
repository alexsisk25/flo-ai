"""Flo core: narration, dictation, vocabulary, and global hotkeys.

All settings/vocabulary are read from the SQLite store at time of use, so
edits made in the web UI apply immediately — no restart needed (except for
hotkey changes, which reload the listener via HotkeyManager.reload()).
"""

import re
import subprocess
import threading
import time

import numpy as np

import cleanup
import learning
import permissions
import stt
import store

SAMPLE_RATE = 16_000

SOUND_START = "/System/Library/Sounds/Tink.aiff"
SOUND_STOP = "/System/Library/Sounds/Pop.aiff"
SOUND_ERROR = "/System/Library/Sounds/Basso.aiff"

# Silence gate. Handing Whisper a buffer of near-silence does not produce an
# empty string — it produces confident nonsense, because the model always
# decodes *something*. Historically that was the single word "You"; with the
# mic live but nobody speaking it becomes a repetition loop. Cheaper and far
# more legible to notice there is no speech and never call the model.
# A FIXED threshold was the wrong design and broke in the field: after a change
# of input device the same speech measured half as loud (rms 0.0153 -> 0.0092)
# and real dictation started being rejected as silence.
#
# What actually separates speech from a live-but-silent mic is not loudness, it
# is STRUCTURE. Speech has loud syllables and quiet gaps, so its frame energies
# span a wide range. A silent mic — or steady fan/traffic noise — sits flat at
# whatever level the hardware gives you, however loud that happens to be.
#
# So: chop the audio into 30 ms frames, and compare a loud frame (90th
# percentile) against the noise floor (10th percentile). Require BOTH a minimum
# absolute level and that dynamic range. Either one alone is fooled — the
# absolute floor by a quiet mic, the ratio by a room that happens to be varying.
FRAME_MS = 30
SPEECH_FLOOR = 0.004      # p90 frame energy below this is not speech at any gain
SPEECH_RATIO = 2.0        # p90 must be this much above the noise floor


def frame_levels(audio, sample_rate=SAMPLE_RATE, ms=FRAME_MS):
    """RMS per short frame. Empty array if the clip is shorter than one frame."""
    n = max(1, int(sample_rate * ms / 1000))
    usable = (len(audio) // n) * n
    if usable == 0:
        return np.empty(0)
    frames = audio[:usable].reshape(-1, n)
    return np.sqrt((frames ** 2).mean(axis=1))


def speech_present(audio, sample_rate=SAMPLE_RATE):
    """(is_speech, metrics) — metrics are logged so a rejection can be argued with."""
    levels = frame_levels(audio, sample_rate)
    if levels.size == 0:
        return False, {"p90": 0.0, "floor": 0.0, "ratio": 0.0}
    p90 = float(np.percentile(levels, 90))
    floor = float(np.percentile(levels, 10))
    ratio = p90 / floor if floor > 1e-9 else float("inf")
    ok = p90 >= SPEECH_FLOOR and ratio >= SPEECH_RATIO
    return ok, {"p90": p90, "floor": floor, "ratio": ratio}

# Whisper's other failure mode on noise: emitting one short fragment hundreds
# of times ("Cluster 07212121212121…"). Left unchecked it reaches the cleanup
# model, which then spends ~30s dutifully tidying garbage while every further
# hotkey press is rejected as "still working".
_REPEAT_RUN = re.compile(r"(.{1,12}?)\1{9,}", re.S)


def looks_degenerate(text: str) -> bool:
    """True if the transcript looks like a decoder repetition loop."""
    if not text:
        return False
    if _REPEAT_RUN.search(text):
        return True
    words = text.split()
    return len(words) >= 20 and len(set(words)) <= max(3, len(words) // 12)


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


def transcribe(audio: np.ndarray, model: str,
               language: str | None = None,
               initial_prompt: str | None = None) -> str:
    """Transcribe with whichever engine suits this Mac (see stt.py)."""
    return stt.transcribe(audio, model, language=language,
                          initial_prompt=initial_prompt,
                          backend=store.get("stt_backend"))


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
            # The replacement is a literal, not a template. Passing it straight
            # to re.sub() made "\1" or "\t" in a fix-up raise re.PatternError —
            # and because this runs in a worker thread, one bad rule silently
            # killed every transcription. A function replacement never expands.
            try:
                text = re.sub(re.escape(r["wrong"]), lambda _m, v=r["right"]: v,
                              text, flags=re.IGNORECASE)
            except re.error as e:                     # malformed `wrong` pattern
                log(f"skipping bad fix-up {r['wrong']!r}: {e}")
        return text, False


class Core:
    def __init__(self):
        from pynput import keyboard

        self.kb = keyboard.Controller()
        self.say_proc: subprocess.Popen | None = None
        self.play_proc: subprocess.Popen | None = None
        self.stream = None
        self.frames: list[np.ndarray] = []
        self.lock = threading.Lock()
        self.on_state = lambda state: None  # 'idle' | 'recording' | 'busy'
        self.on_level = lambda rms: None    # mic level while recording
        # 'loading' until warm_up finishes. On a fresh machine that means a
        # ~1.6 GB download, during which the app otherwise looks inert.
        self.model_state = "loading"
        self.model_error = None
        self.on_command = lambda text: None  # console voice command transcript
        self.command_next = False  # route the next transcript to on_command
        self.watcher = learning.CorrectionWatcher()  # learns from your edits

    # ------------------------------------------------------------ audio out
    # Two ways Flo makes noise: `say` (narration) and `afplay` (replaying a
    # dictation recording). Both are held so the dashboard can stop them.

    def speaking(self) -> bool:
        return self.say_proc is not None and self.say_proc.poll() is None

    def playing(self) -> bool:
        return self.play_proc is not None and self.play_proc.poll() is None

    def busy_audio(self) -> bool:
        return self.speaking() or self.playing()

    def stop_speech(self) -> None:
        if self.speaking():
            self.say_proc.terminate()
        self.say_proc = None

    def stop_playback(self) -> None:
        if self.playing():
            self.play_proc.terminate()
        self.play_proc = None

    def stop_all(self) -> None:
        self.stop_speech()
        self.stop_playback()

    def play_file(self, path: str) -> None:
        """Replay a recorded dictation, keeping the handle so it can be cut."""
        self.stop_all()
        self.play_proc = subprocess.Popen(
            ["afplay", path], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)

    def _copy_selection(self) -> str:
        from pynput.keyboard import Key

        saved = get_clipboard()
        try:
            set_clipboard("")
            time.sleep(0.30)  # let hotkey modifiers be released
            with self.kb.pressed(Key.cmd):
                self.kb.press("c")
                self.kb.release("c")
            time.sleep(0.30)
            return get_clipboard()
        finally:
            set_clipboard(saved)   # restore even if the copy raises

    def speak(self, text: str, record_history: bool = True) -> None:
        self.stop_all()
        rate = int(store.get_valid("tts_rate"))
        voice = store.get_valid("tts_voice")
        cmd = ["say", "-r", str(rate)] + (["-v", voice] if voice else [])
        try:
            self.say_proc = subprocess.Popen(cmd + ["-f", "-"],
                                             stdin=subprocess.PIPE)
            self.say_proc.stdin.write(text.encode())
            self.say_proc.stdin.close()
        except (OSError, ValueError) as e:
            # a deleted voice, or `say` refusing the text
            log(f"Narration failed: {e}")
            play_sound(SOUND_ERROR)
            self.say_proc = None
            return
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
        info = stt.describe(store.get("stt_backend"))
        model = stt.canonical(store.get("stt_model"))
        log(f"{info['chip']} detected → {info['backend']} on {info['accelerator']}")
        log(f"Loading speech model {model}… (first run downloads it, ~1.6 GB)")
        self.model_state = "loading"
        try:
            transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), model)
        except Exception as e:
            self.model_state = "error"
            self.model_error = f"{type(e).__name__}: {e}"
            log(f"Speech model failed to load: {self.model_error}")
            raise
        self.model_state = "ready"
        log("Speech model ready.")

    def toggle_dictate(self) -> None:
        # Non-blocking: transcription can take seconds while holding this lock.
        # Blocking here meant a hotkey press during transcription queued up and
        # then started an unexpected recording once the lock freed.
        if not self.lock.acquire(blocking=False):
            log("Still working on the last dictation — ignoring.")
            return
        try:
            if self.recording():
                self._stop_and_type()
            else:
                self._start_recording()
        finally:
            self.lock.release()

    def toggle_command(self) -> None:
        """Like dictation, but the transcript goes to the Console bridge
        (on_command) instead of being typed into the frontmost app."""
        if not self.lock.acquire(blocking=False):
            log("Still working on the last dictation — ignoring.")
            return
        try:
            if self.recording():
                self._stop_and_type()
            else:
                self.command_next = True
                self._start_recording()
        finally:
            self.lock.release()

    # ------------------------------------------------ push-to-talk dictation
    # Hold a key to record, release to type. Unlike toggle_dictate, start and
    # stop are separate events driven by the key's press and release.

    def ptt_start(self) -> None:
        """Begin a push-to-talk recording. Ignored if a dictation is in flight."""
        if not self.lock.acquire(blocking=False):
            log("Still working on the last dictation — ignoring.")
            return
        try:
            if not self.recording():
                self._start_recording()
        finally:
            self.lock.release()

    def ptt_stop(self) -> None:
        """End a push-to-talk recording and type the transcript. Blocks (runs in
        its own thread) until any in-flight start or transcription completes."""
        with self.lock:
            if self.recording():
                self._stop_and_type()

    def ptt_cancel(self) -> None:
        """Abort the current recording without transcribing — used when the key
        turned out to be part of a chord (e.g. Right Option + S to narrate)."""
        with self.lock:
            if not self.recording():
                return
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                log(f"Error closing the microphone: {e}")
            self.stream = None
            self.frames = []
            self.command_next = False
            self.on_state("idle")

    def _start_recording(self) -> None:
        import sounddevice as sd

        self.stop_all()
        self.frames = []

        warned = []

        def on_audio(indata, *_):
            self.frames.append(indata.copy())
            try:
                self.on_level(float(np.sqrt(np.mean(indata ** 2))))
            except Exception as e:
                # Runs per audio frame, so log once per recording rather than
                # thousands of times — but never nothing.
                if not warned:
                    warned.append(True)
                    log(f"Level meter failed: {type(e).__name__}: {e}")

        def open_stream():
            s = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                               dtype="float32", callback=on_audio)
            try:
                s.start()
            except Exception:
                s.close()          # never leave a half-open stream behind
                raise
            return s

        # If opening the mic fails (permission denied, device in use), leave
        # self.stream as None. Assigning first meant recording() reported True
        # forever and the next hotkey press tried to stop a dead stream.
        try:
            stream = open_stream()
        except Exception as first:
            # PortAudio enumerates audio devices once, when it initialises. If
            # the default input changed since Flo started — headphones in, a
            # Bluetooth mic, a meeting grabbing the device — those cached
            # indices go stale and EVERY open fails with a bare internal error.
            # The process is then dead to dictation until it restarts, which is
            # exactly what it looked like: hotkeys firing, nothing recording.
            # Rescanning is cheap; do it and try once more.
            log(f"Microphone open failed ({first}); rescanning audio devices…")
            try:
                sd._terminate()
                sd._initialize()
                stream = open_stream()
            except Exception as second:
                log(f"Could not open the microphone: {second}")
                play_sound(SOUND_ERROR)
                self.on_state("idle")
                return
            log("Recovered after rescanning audio devices.")
        self.stream = stream
        play_sound(SOUND_START)
        self.on_state("recording")
        log("Recording…")

    def _stop_and_type(self) -> None:
        was_command = self.command_next
        self.command_next = False
        try:
            self.stream.stop()
            self.stream.close()
        except Exception as e:
            log(f"Error closing the microphone: {e}")
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
            heard, m = speech_present(audio)
            # Always log the numbers, so a wrong decision can be argued with
            # rather than guessed at.
            log(f"Level: p90 {m['p90']:.4f}, floor {m['floor']:.4f}, "
                f"ratio {m['ratio']:.1f}x")
            if not heard:
                why = ("too quiet" if m["p90"] < SPEECH_FLOOR
                       else "no speech pattern — flat, like room noise")
                log(f"Heard nothing ({why}) — not transcribing.")
                return
            log(f"Transcribing {secs:.1f}s…")
            t0 = time.time()
            t_stt = t_clean = 0.0
            try:
                text = transcribe(
                    audio,
                    store.get("stt_model"),
                    language=store.get("stt_language") or None,
                    initial_prompt=Vocabulary.initial_prompt(),
                )
            except Exception as e:
                # model download failed, disk full, corrupt weights… don't die
                # silently in a worker thread: chime and say so in the log.
                log(f"Transcription failed: {type(e).__name__}: {e}")
                play_sound(SOUND_ERROR)
                return
            if looks_degenerate(text):
                log(f"Discarded a degenerate transcript "
                    f"({len(text)} chars, {len(set(text.split()))} distinct "
                    f"words): {text[:60]!r}…")
                play_sound(SOUND_ERROR)
                return
            t_stt = time.time() - t0
            text, used_snippet = Vocabulary.apply(text)
            # Local AI cleanup (grammar, filler, self-corrections). Snippets are
            # canned and commands are raw match phrases, so skip both.
            if (text and not used_snippet and not was_command
                    and cleanup.enabled() and cleanup.state() == "ready"):
                terms = [w["word"] for w in store.words_list()]
                rules = [store.preference_instruction(p)
                         for p in store.preferences_top()]
                t1 = time.time()
                cleaned = cleanup.clean(text, terms=terms, rules=rules)
                t_clean = time.time() - t1
                if cleaned != text:
                    log(f"cleanup: {text!r} → {cleaned!r}")
                text = cleaned
            # Break the time down. "It took 30 seconds" is not actionable;
            # "transcribe 27s, cleanup 1s" says the models were paged out.
            log(f"({time.time() - t0:.1f}s total: transcribe {t_stt:.1f}s, "
                f"cleanup {t_clean:.1f}s) → {text!r}")
            if not text:
                return
            audio_path = self._save_audio(audio)
            if was_command:
                store.history_add("command", text, secs,
                                  audio_path=audio_path)
                threading.Thread(target=self.on_command, args=(text,),
                                 daemon=True).start()
                return
            store.history_add("dictation", text, secs,
                              snippet=used_snippet, audio_path=audio_path)
            store.prune_recordings()   # keep only the newest few .wav files
            self._type(text + " ")
            # Watch the field for edits and learn from them (best-effort).
            self.watcher.watch(text)
        finally:
            self.on_state("idle")

    @staticmethod
    def _save_audio(audio: np.ndarray) -> str:
        import soundfile as sf

        # Second resolution collided: two dictations inside the same second
        # wrote the same file, so one clip overwrote the other and deleting
        # either history row unlinked the survivor's audio too.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = store.RECORDINGS / f"dictation-{stamp}.wav"
        n = 1
        while path.exists():
            path = store.RECORDINGS / f"dictation-{stamp}-{n}.wav"
            n += 1
        sf.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
        return str(path)

    @staticmethod
    def _frontmost() -> str:
        """Name of the app that will receive the paste, for the log."""
        try:
            import AppKit
            app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            return app.localizedName() if app else "unknown"
        except Exception as e:
            return f"unknown ({type(e).__name__})"

    def _type(self, text: str) -> None:
        from pynput.keyboard import Key

        log(f"Typing into: {self._frontmost()}")
        saved = get_clipboard()
        try:
            set_clipboard(text)
            time.sleep(0.25)   # slower apps read the clipboard late; 0.15 dropped pastes
            with self.kb.pressed(Key.cmd):
                self.kb.press("v")
                self.kb.release("v")
            time.sleep(0.75)   # let the paste land before the clipboard is restored
        finally:
            set_clipboard(saved)   # never strand the transcript in the clipboard


# macOS ANSI virtual keycodes for the letter keys.
#
# Option is a TEXT-COMPOSITION modifier on macOS: Option+S does not deliver "s",
# it delivers "ß" (and Option+E, Option+N etc. arm dead keys). pynput's
# GlobalHotKeys matches on the composed character, so a binding like "<alt>+s"
# binds without error, reports itself active, and is structurally incapable of
# ever firing. Virtual keycodes are unaffected by the modifier, so an Option
# chord has to be matched on vk instead.
_MAC_VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45,
    "m": 46,
}

_ALT_LETTER = re.compile(r"^<alt>\+([a-z])$", re.IGNORECASE)


class HotkeyManager:
    """Global hotkeys.

    Narrate and the (dormant) console command are ordinary combo hotkeys via
    pynput's GlobalHotKeys, re-bindable from the dashboard. Dictation is
    different: it is PUSH-TO-TALK on the Right Option key — hold to record,
    release to type — driven by a raw key listener because a held modifier can't
    be a GlobalHotKeys combo. A Right Option chord (e.g. Right Option + S to
    narrate) cancels the nascent recording so the two never collide.
    """

    DICTATE_LABEL = "Right Option (hold)"
    _DEBOUNCE = 0.12   # seconds to hold before recording; lets a chord cancel first

    def __init__(self, core: Core):
        self.core = core
        self.listener = None      # GlobalHotKeys: narrate + command
        self.ptt = None           # raw Listener: push-to-talk dictation
        self._alt_down = False
        self._any_alt = False       # either Option key, for narrate chords
        self._chord = False
        self._speak_vk = None       # set in start() for <alt>+letter bindings
        self._on_speak = lambda: None
        self._last_speak = 0.0
        self._dictating = False
        self._timer = None

    def start(self) -> None:
        """Bind the hotkeys. Never raises: an unusable combo falls back to the
        default rather than killing the listener (or, at launch, the process —
        which launchd would then respawn forever)."""
        from pynput import keyboard

        self.stop()
        # get_valid() heals a database holding a combo pynput cannot parse
        speak = store.get_valid("hotkey_speak")
        command = store.get_valid("hotkey_command")

        def on_speak():
            threading.Thread(target=self.core.toggle_speak, daemon=True).start()

        def on_command():
            threading.Thread(target=self.core.toggle_command, daemon=True).start()

        # An <alt>+letter combo cannot work through GlobalHotKeys on macOS (see
        # _MAC_VK above), so handle it in the raw listener and keep it out of
        # the combo map entirely rather than registering a binding that lies.
        self._speak_vk = None
        combos = {speak: on_speak, command: on_command}
        m = _ALT_LETTER.match(speak or "")
        if m and m.group(1).lower() in _MAC_VK:
            self._speak_vk = _MAC_VK[m.group(1).lower()]
            self._on_speak = on_speak
            combos.pop(speak, None)

        try:
            self.listener = keyboard.GlobalHotKeys(combos)
            self.listener.start()
        except Exception as e:
            # e.g. the combos collide, or macOS refuses the tap
            self.listener = None
            log(f"Could not bind hotkeys ({speak}, {command}): {e}")
            if (speak, command) == (store.DEFAULTS["hotkey_speak"],
                                    store.DEFAULTS["hotkey_command"]):
                log("Defaults failed too — check Accessibility permission.")
                return
            log("Falling back to the default hotkeys.")
            store.set_setting("hotkey_speak", store.DEFAULTS["hotkey_speak"])
            store.set_setting("hotkey_command", store.DEFAULTS["hotkey_command"])
            self.start()
            return

        # Push-to-talk dictation on Right Option. Isolated so a failure here can't
        # take the combo hotkeys (or the process) down with it.
        try:
            self._start_ptt(keyboard)
        except Exception as e:
            log(f"Push-to-talk listener failed to start: {e}")

        # pynput binds happily without Accessibility and then never fires. Saying
        # "Hotkeys active" here would be a lie, and it was the single most common
        # way this app appeared broken to a new user.
        if not permissions.accessibility_trusted():
            log(f"Hotkeys registered ({speak} narrate, {self.DICTATE_LABEL} "
                f"dictate, {command} command) but they will NOT fire: Flo has no "
                f"Accessibility permission.")
            log("Fix: System Settings → Privacy & Security → Accessibility, "
                "add Flo (or your terminal), then restart Flo.")
            return
        log(f"Hotkeys active: {speak} (narrate), {self.DICTATE_LABEL} "
            f"(dictate, push-to-talk), {command} (console command)")

    def _start_ptt(self, keyboard) -> None:
        Key = keyboard.Key

        def on_press(key):
            if key in (Key.alt, Key.alt_l, Key.alt_r):
                self._any_alt = True
            elif (self._any_alt and self._speak_vk is not None
                    and getattr(key, "vk", None) == self._speak_vk):
                now = time.monotonic()
                if now - self._last_speak > 0.4:     # ignore key repeat
                    self._last_speak = now
                    self._on_speak()
            if key == Key.alt_r:
                if not self._alt_down:
                    self._alt_down = True
                    self._chord = False
                    self._timer = threading.Timer(self._DEBOUNCE, self._begin)
                    self._timer.start()
            elif self._alt_down and not self._chord:
                # Right Option + another key = a chord (e.g. narrate), not dictation.
                self._chord = True
                if self._timer:
                    self._timer.cancel()
                if self._dictating:
                    self._dictating = False
                    threading.Thread(target=self.core.ptt_cancel,
                                     daemon=True).start()

        def on_release(key):
            if key in (Key.alt, Key.alt_l, Key.alt_r):
                self._any_alt = False
            if key == Key.alt_r:
                self._alt_down = False
                if self._timer:
                    self._timer.cancel()
                if self._dictating:
                    self._dictating = False
                    threading.Thread(target=self.core.ptt_stop,
                                     daemon=True).start()
                self._chord = False

        self.ptt = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.ptt.start()

    def _begin(self) -> None:
        """Fires once Right Option has been held past the debounce with no chord."""
        if self._alt_down and not self._chord:
            self._dictating = True
            threading.Thread(target=self.core.ptt_start, daemon=True).start()

    def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self.listener:
            self.listener.stop()
            self.listener = None
        if self.ptt:
            self.ptt.stop()
            self.ptt = None

    def reload(self) -> None:
        self.start()
