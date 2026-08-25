"""The silence gate must survive a change of microphone.

Whisper does not return an empty string for silence — it invents. That produced
"You" in one incident and a 400-character "nuevo nuevo nuevo" loop in another.
The first gate used an absolute RMS threshold tuned on one machine, and broke in
the field when the input device changed and the same speech measured half as
loud: real dictation started being rejected.

What separates speech from a live-but-silent mic is structure, not loudness.
Speech has loud syllables and quiet gaps. A silent mic, or a fan, is flat at
whatever level the hardware happens to give you.
"""

import numpy as np

import core

SR = core.SAMPLE_RATE
RNG = np.random.default_rng(7)


def speech_like(seconds, amplitude):
    """Syllables separated by gaps — the shape that makes speech speech."""
    t = np.arange(int(SR * seconds)) / SR
    env = np.zeros_like(t)
    for start in np.arange(0, seconds, 0.35):
        i, j = int(start * SR), int(start * SR) + int(0.18 * SR)
        window = np.hanning(max(1, j - i))
        env[i:j] = window[:len(env[i:j])]
    noise = 0.0005 * RNG.standard_normal(len(t))
    return (amplitude * env * np.sin(2 * np.pi * 180 * t) + noise).astype(np.float32)


def steady(seconds, amplitude):
    """Flat noise: a live mic in a silent room, or a fan."""
    return (amplitude * RNG.standard_normal(int(SR * seconds))).astype(np.float32)


def test_loud_speech_is_heard():
    assert core.speech_present(speech_like(4, 0.06))[0]


def test_quiet_speech_is_heard():
    """The exact regression: after an input-device change the same speech
    measured about half as loud and the old absolute threshold rejected it."""
    assert core.speech_present(speech_like(4, 0.025))[0]


def test_very_quiet_speech_is_still_heard():
    assert core.speech_present(speech_like(4, 0.012))[0]


def test_a_silent_mic_is_rejected():
    assert not core.speech_present(steady(4, 0.002))[0]


def test_a_loud_steady_noise_floor_is_rejected():
    """A fan can be LOUDER than real speech. No absolute threshold can tell
    them apart; the dynamic range can."""
    heard, m = core.speech_present(steady(4, 0.02))
    assert not heard
    assert m["p90"] > 0.012          # genuinely louder than the quiet speech above
    assert m["ratio"] < core.SPEECH_RATIO


def test_near_digital_silence_is_rejected():
    assert not core.speech_present(steady(4, 0.00002))[0]


def test_a_clip_shorter_than_one_frame_is_not_speech():
    assert not core.speech_present(np.zeros(3, dtype=np.float32))[0]


def test_metrics_are_always_reported():
    """Every rejection must be explainable from the log, not guessed at."""
    _, m = core.speech_present(speech_like(2, 0.03))
    assert set(m) == {"p90", "floor", "ratio"}
