"""The corpus learner proposes dictionary entries from your own writing.

Every entry it adds is fed to Whisper as a hint, so a junk entry actively makes
transcription worse. These tests pin down what counts as jargon and what does
not.
"""

import corpus


def counts(text):
    return corpus.candidates(text)


def test_finds_internal_caps_and_acronyms():
    c = counts("We checked CoStar and the NOI held up. CoStar again.")
    assert c["CoStar"] == 2
    assert c["NOI"] == 1


def test_finds_proper_nouns_mid_sentence():
    assert counts("The comps came from Yardi last week.")["Yardi"] == 1


def test_ignores_sentence_initial_capitals():
    """A capital at the start of a sentence carries no information — every
    sentence starts with one, jargon or not."""
    assert counts("Yardi is the system of record.")["Yardi"] == 0


def test_ignores_common_capitalised_words():
    c = counts("The seller said Thursday. They want it by Friday. Thanks.")
    for word in ("The", "They", "Thursday", "Friday", "Thanks"):
        assert c[word] == 0


def test_ignores_ordinary_lowercase_words():
    c = counts("we should probably close on the building next week")
    assert not c


def test_plural_acronyms_count():
    assert counts("He sent two LOIs and the REITs filed.")["LOIs"] == 1


def test_scan_rejects_a_missing_folder():
    try:
        corpus.scan("/nope/not/a/real/folder")
    except NotADirectoryError:
        return
    raise AssertionError("expected NotADirectoryError")
