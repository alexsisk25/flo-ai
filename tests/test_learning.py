"""The learning loop's pure diff logic — what Flo learns from your edits."""

import learning


def test_detects_single_spelling_correction():
    assert learning.corrections("I met with Catherine", "I met with Katharine") == \
        [("Catherine", "Katharine")]


def test_ignores_case_only_change():
    assert learning.corrections("deploy to kubernetes", "deploy to Kubernetes") == []


def test_ignores_unrelated_word_choice():
    # "quick" -> "slow" is a word choice, not a spelling fix.
    assert learning.corrections("the quick brown fox", "the slow brown fox") == []


def test_multiple_corrections():
    got = learning.corrections("email Jon about Postgress", "email John about Postgres")
    assert ("Jon", "John") in got
    assert ("Postgress", "Postgres") in got


def test_word_swap_preference():
    got = learning.preferences("we should utilize the tool", "we should use the tool")
    assert ("word_swap", "utilize", "use") in got


def test_spelling_fix_is_not_a_preference():
    got = learning.preferences("email Katharyn", "email Katharine")
    assert not [p for p in got if p[0] == "word_swap"]


def test_phrase_cut_preference():
    got = learning.preferences("so basically we ship tonight", "we ship tonight")
    assert ("phrase_cut", "so basically", "") in got


def test_no_change_learns_nothing():
    assert learning.corrections("same text", "same text") == []
    assert learning.preferences("same text", "same text") == []


def test_levenshtein():
    assert learning.levenshtein("kitten", "sitting") == 3
    assert learning.levenshtein("", "abc") == 3
    assert learning.levenshtein("abc", "abc") == 0


def test_tokenize_strips_punctuation():
    assert learning.tokenize("Hello, world! It's a test-run.") == \
        ["Hello", "world", "It's", "a", "test-run"]


def test_preferences_store_roundtrip(db):
    db.preferences_learn("word_swap", "Utilize", "Use")
    db.preferences_learn("word_swap", "utilize", "use")   # same, case-normalized
    top = db.preferences_top()
    assert len(top) == 1
    assert top[0]["freq"] == 2
    assert top[0]["from_text"] == "utilize"
    assert db.preference_instruction(top[0]) == 'Prefer "use" over "utilize".'
