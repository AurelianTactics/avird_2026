"""Tests for the /health route and the underlying DB probe.

The route tests use FastAPI dependency overrides — they don't require a
running Postgres. The probe test exercises check_db() directly against
an unreachable host to prove it never raises and reports "down" cleanly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app.db import check_db
from app.main import app


@pytest.fixture(autouse=True)
def _reset_pool_state():
    db_module._pool = None
    yield
    db_module._pool = None


def _override(value: str):
    app.dependency_overrides[check_db] = lambda: value


def _clear_override():
    app.dependency_overrides.clear()


def test_health_returns_db_ok_when_pool_succeeds():
    _override("ok")
    try:
        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "db": "ok"}
    finally:
        _clear_override()


def test_health_returns_db_down_when_pool_fails():
    _override("down")
    try:
        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "db": "down"}
    finally:
        _clear_override()


def test_health_does_not_require_auth_headers():
    _override("ok")
    try:
        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
    finally:
        _clear_override()


async def test_check_db_returns_down_on_unreachable_host(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/nope")
    result = await check_db()
    assert result == "down"


async def test_check_db_returns_down_when_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = await check_db()
    assert result == "down"
