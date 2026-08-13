"""Option-key hotkeys on macOS.

Option is a text-composition modifier: pressing Option+S delivers "ß", not "s".
pynput's GlobalHotKeys matches the composed character, so "<alt>+s" binds
cleanly, logs itself as active, and can never fire. Narration shipped broken
this way and the app reported it as working. These tests pin the routing that
fixes it.
"""

import core


def test_alt_letter_bindings_are_recognised():
    assert core._ALT_LETTER.match("<alt>+s").group(1) == "s"
    assert core._ALT_LETTER.match("<alt>+S").group(1) == "S"


def test_combos_with_other_modifiers_are_left_alone():
    """<ctrl>+<alt>+c works through GlobalHotKeys because Ctrl suppresses
    composition, so it must NOT be rerouted to the raw listener."""
    assert core._ALT_LETTER.match("<ctrl>+<alt>+c") is None
    assert core._ALT_LETTER.match("<cmd>+<shift>+v") is None


def test_s_maps_to_the_keycode_macos_actually_sends():
    """Verified live: pressing Option+S reports char='ß', vk=1."""
    assert core._MAC_VK["s"] == 1


def test_letter_table_covers_the_alphabet_keys_we_offer():
    for letter in "asdfhgzxcvbqweryto uipljkn m".replace(" ", ""):
        assert letter in core._MAC_VK, letter
