"""What a stranger's Mac sees on first launch.

v1.0.0 crash-looped here. `WalnutApp.__init__` called `self.menu.insert(0, …)`
when Accessibility was missing; `rumps.Menu` is an OrderedDict with no `insert`.
The branch only runs for users who haven't granted the permission — which is
everyone, once — so every test on the developer's machine passed while the app
was unusable for anyone new.

Nothing here mocks rumps. Mocking the library would re-create the original bug:
the whole failure was an assumption about that library's API.
"""

import inspect
from pathlib import Path

import pytest
import rumps

REPO = Path(__file__).resolve().parent.parent


def _titles(items):
    return [i.title for i in items if i is not None]


def _handlers(app_module, obj):
    return {name: getattr(obj, name) for name in (
        "fix_permissions", "open_dashboard", "menu_dictate",
        "menu_speak", "menu_stop")}


class _Handlers:
    """Stand-ins with the same names WalnutApp binds."""
    def fix_permissions(self, _): pass
    def open_dashboard(self, _): pass
    def menu_dictate(self, _): pass
    def menu_speak(self, _): pass
    def menu_stop(self, _): pass


# --------------------------------------------------------------- build_menu

def test_menu_warns_when_accessibility_is_denied():
    import app

    items = app.build_menu(False, "<ctrl>+<alt>+s", "<ctrl>+<alt>+d",
                           _handlers(app, _Handlers()))
    titles = _titles(items)
    assert titles[0].startswith("⚠️")           # first thing the user sees
    assert "Accessibility" in titles[0]
    assert "Open Walnut Dashboard" in titles


def test_menu_is_clean_when_accessibility_is_granted():
    import app

    items = app.build_menu(True, "<ctrl>+<alt>+s", "<ctrl>+<alt>+d",
                           _handlers(app, _Handlers()))
    titles = _titles(items)
    assert not any(t.startswith("⚠️") for t in titles)
    assert titles[0] == "Open Walnut Dashboard"


def test_every_menu_item_has_a_callable_callback():
    """A typo'd handler name would only surface when the user clicked it."""
    import app

    for trusted in (True, False):
        for item in app.build_menu(trusted, "<ctrl>+<alt>+s", "<ctrl>+<alt>+d",
                                   _handlers(app, _Handlers())):
            if item is not None:
                assert callable(item._menuitem.action or item.callback), item.title


def test_walnut_app_binds_every_handler_build_menu_asks_for():
    """build_menu() takes handlers by name; WalnutApp must actually have them."""
    import app

    for name in ("fix_permissions", "open_dashboard", "menu_dictate",
                 "menu_speak", "menu_stop"):
        assert callable(getattr(app.WalnutApp, name)), name


# ------------------------------------------------------------ the real thing

def test_walnut_app_constructs_with_accessibility_denied(
        first_run, free_port, monkeypatch):
    """The test that would have caught the v1.0.0 crash loop.

    Constructs the real WalnutApp — real rumps, real menu assignment — in the
    state every new user is in. Overlay is stubbed because it talks to AppKit's
    main run loop, which pytest does not have; nothing else is.
    """
    import app
    import store

    store.set_setting("port", str(free_port))

    class _NoOverlay:
        def set_level(self, rms): pass
        def show(self): pass
        def hide(self): pass

    monkeypatch.setattr(app.overlay, "Overlay", _NoOverlay)
    monkeypatch.setattr(app.server, "run", lambda port: None)   # don't bind
    monkeypatch.setattr(app.WalnutApp, "_guarded", staticmethod(lambda fn, *a: None))

    instance = app.WalnutApp()          # this raised AttributeError in v1.0.0
    try:
        titles = [k for k in instance.menu.keys()]
        assert any("Accessibility" in t for t in titles), titles
        assert titles[0].startswith("⚠️")
    finally:
        instance.hotkeys.stop()
        instance.core.stop_all()


def test_walnut_app_constructs_when_trusted(db, free_port, monkeypatch):
    import app
    import permissions
    import store

    monkeypatch.setattr(permissions, "accessibility_trusted", lambda: True)
    store.set_setting("port", str(free_port))

    class _NoOverlay:
        def set_level(self, rms): pass
        def show(self): pass
        def hide(self): pass

    monkeypatch.setattr(app.overlay, "Overlay", _NoOverlay)
    monkeypatch.setattr(app.server, "run", lambda port: None)
    monkeypatch.setattr(app.WalnutApp, "_guarded", staticmethod(lambda fn, *a: None))

    instance = app.WalnutApp()
    try:
        assert not any("Accessibility" in t for t in instance.menu.keys())
    finally:
        instance.hotkeys.stop()
        instance.core.stop_all()


# ------------------------------------------------------- status under first run

def test_status_endpoint_tells_the_truth_on_first_run(first_run, client):
    d = client.get("/api/status").get_json()
    assert d["accessibility"] is False
    assert d["accessibility_hint"]              # non-empty, actionable


def test_dashboard_is_empty_but_serves_on_first_run(first_run, client):
    assert client.get("/").status_code == 200
    d = client.get("/api/dashboard").get_json()
    assert d["dictation_sessions"] == 0 and d["readback_sessions"] == 0


# --------------------------------------------------------- assumption guards

def test_rumps_menu_still_has_no_insert():
    """Pin the actual mistake. If a future rumps grows .insert(), this fails
    loudly and someone re-reads the code rather than trusting folklore."""
    from rumps.rumps import Menu

    assert not hasattr(Menu(), "insert")
    assert hasattr(Menu(), "insert_before")


def test_source_never_calls_menu_insert():
    """Parse, don't grep: the docstrings here quote the bug on purpose."""
    import ast

    tree = ast.parse((REPO / "app.py").read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "insert"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "menu"):
            pytest.fail(f"app.py calls .menu.insert() at line {node.lineno}")


@pytest.mark.parametrize("call,params", [
    (rumps.App.__init__, {"name", "title", "icon", "template", "menu", "quit_button"}),
    (rumps.MenuItem.__init__, {"title", "callback", "key", "icon", "dimensions", "template"}),
    (rumps.alert, {"title", "message", "ok", "cancel", "other", "icon_path"}),
])
def test_rumps_signatures_are_what_we_assume(call, params):
    """Every rumps API Walnut calls, checked against the installed library."""
    actual = set(inspect.signature(call).parameters) - {"self"}
    assert params <= actual or actual <= params, actual
