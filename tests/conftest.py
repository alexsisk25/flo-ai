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
