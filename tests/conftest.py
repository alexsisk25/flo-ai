"""Point Walnut at a throwaway database for every test."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh, isolated store. Never touches the real walnut.db."""
    import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "walnut.db")
    monkeypatch.setattr(store, "RECORDINGS", tmp_path / "recordings")
    store.RECORDINGS.mkdir()
    store.init()
    return store


@pytest.fixture
def first_run(db, monkeypatch):
    """The state a stranger's Mac is in, which the developer's never is.

    Accessibility denied, empty database, model still downloading. Two
    crash-loop bugs shipped because nothing forced this state. Use it for any
    branch only a first-time user reaches.

    `request_accessibility` is neutered: it opens a system modal that would
    hang the suite waiting for a human.
    """
    import permissions

    monkeypatch.setattr(permissions, "accessibility_trusted", lambda: False)
    monkeypatch.setattr(permissions, "request_accessibility", lambda: False)
    # summary() calls accessibility_trusted(), so it follows automatically.
    return db


@pytest.fixture
def free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def client(db):
    """Flask test client wired to a real Core, on the throwaway store."""
    import core
    import server

    server.CORE = core.Core()
    server.HOTKEYS = core.HotkeyManager(server.CORE)
    server.HOTKEYS.start()
    yield server.app.test_client()
    server.HOTKEYS.stop()
    server.CORE.stop_all()
