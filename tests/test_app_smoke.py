"""FastAPI app smoke tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "HealthCoachAgent"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "providers" in body
    # Roles must be present even if empty
    assert "main_chat" in body["providers"]
    assert "vision" in body["providers"]
    assert "router" in body["providers"]
    # New: langfuse + storage fields
    assert "langfuse" in body
    assert "enabled" in body["langfuse"]
    assert "storage" in body
