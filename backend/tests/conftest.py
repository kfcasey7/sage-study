"""Test fixtures: isolated data dir, a fake API key, and a fake Claude that returns schema-valid
responses (so the full session flow runs without network access or cost)."""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from sage import claude_client, config, db, keystore
from sage.services import sessions as S

from sage.fake_claude import FakeClaude, FakeMessage, FakeText  # noqa: F401 - re-exported for tests


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    db.init_db()
    S._prefix_cache.clear()
    yield tmp_path


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(keystore, "get_api_key", lambda: ("sk-ant-test-key-123456", "env"))

@pytest.fixture
def fake_claude(monkeypatch, api_key):
    fake = FakeClaude()
    monkeypatch.setattr(claude_client, "_send", fake.send)
    return fake


@pytest.fixture
def client(fake_claude):
    from sage.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8765", headers={"x-sage-client": "1"}) as c:
        yield c


def wait_for(fn: Callable[[], Any], timeout: float = 10.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")
