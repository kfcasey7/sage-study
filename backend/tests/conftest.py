"""Test fixtures: isolated data dir and a fake Claude Code CLI that returns schema-valid responses
(so the full session flow runs without calling Claude)."""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from sage import config, db, llm_client, runtime
from sage.fake_claude import FakeClaude, cli_error, cli_result  # noqa: F401 - re-exported for tests
from sage.services import sessions as S


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "LLM_TMP_DIR", tmp_path / "llm_tmp")
    monkeypatch.setattr(runtime, "port", 8765)
    monkeypatch.setattr(runtime, "window_mode", "window")
    db.init_db()
    S._material_cache.clear()
    # Never touch the real credential store: keep the YouTube key in memory.
    from sage import secrets

    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get_youtube_key", lambda: store.get("key"))
    monkeypatch.setattr(secrets, "set_youtube_key", lambda key: store.__setitem__("key", key))
    monkeypatch.setattr(secrets, "delete_youtube_key", lambda: store.pop("key", None))
    yield tmp_path


@pytest.fixture
def fake_claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(llm_client, "run_cli", fake.send)
    return fake


@pytest.fixture
def client(fake_claude):
    from sage.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8765", headers={"x-sage-client": "1", "x-sage-token": runtime.token}) as c:
        yield c


def wait_for(fn: Callable[[], Any], timeout: float = 10.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


from .web_mock import web  # noqa: E402,F401 - fixture: a fake internet for link and YouTube tests
