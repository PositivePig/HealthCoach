"""MCP protocol tests for the notify server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest


@pytest.fixture
async def temp_notify(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "n_mcp.db"))
    monkeypatch.setenv("NOTIFY_FILE_PATH", str(tmp_path / "out.jsonl"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.notify.channels import reset_registry
    reset_registry()

    from backend.app.db import init_db
    await init_db()

    yield tmp_path
    await eng.dispose_engine()


async def _call(server, name, args):
    return await server.request_handlers[CallToolRequest](
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.mark.asyncio
async def test_list_tools(temp_notify):
    from backend.app.mcp_servers.notify.server import build_server, TOOLS
    server = build_server()
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    names = {t.name for t in result.root.tools}
    assert names == {t.name for t in TOOLS}
    for must_have in {
        "list_channels", "dispatch_pending", "dispatch_one",
        "test_channel", "get_status",
    }:
        assert must_have in names


@pytest.mark.asyncio
async def test_list_channels_via_mcp(temp_notify):
    from backend.app.mcp_servers.notify.server import build_server
    server = build_server()
    r = await _call(server, "list_channels", {})
    body = json.loads(r.root.content[0].text)
    names = {c["name"] for c in body}
    assert names == {"console", "file", "email"}
    # Console + file are always available
    by_name = {c["name"]: c for c in body}
    assert by_name["console"]["available"] is True
    assert by_name["file"]["available"] is True


@pytest.mark.asyncio
async def test_test_channel_file_writes(temp_notify):
    from backend.app.mcp_servers.notify.server import build_server
    server = build_server()
    r = await _call(server, "test_channel", {
        "channel": "file",
        "user_id": "alice",
        "title": "T",
        "body": "B",
    })
    body = json.loads(r.root.content[0].text)
    assert body["ok"] is True
    out = (temp_notify / "out.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(out)
    assert rec["user_id"] == "alice"


@pytest.mark.asyncio
async def test_test_channel_email_unavailable_returns_error(temp_notify, monkeypatch):
    # Ensure no SMTP env
    for k in ("NOTIFY_SMTP_HOST", "NOTIFY_SMTP_USER", "NOTIFY_SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    from backend.app.notify.channels import reset_registry
    reset_registry()

    from backend.app.mcp_servers.notify.server import build_server
    server = build_server()
    r = await _call(server, "test_channel", {"channel": "email"})
    body = json.loads(r.root.content[0].text)
    assert body["ok"] is False
    assert "not configured" in body["error"]


@pytest.mark.asyncio
async def test_dispatch_pending_via_mcp(temp_notify):
    from backend.app.db import session_scope, repository as repo
    from backend.app.db.models import Notification
    async with session_scope() as s:
        await repo.upsert_user(s, "u1")
        n = Notification(
            user_id="u1", kind="test", title="hi", body="body",
            status="approved", channel="file",
        )
        s.add(n)
        await s.flush()

    from backend.app.mcp_servers.notify.server import build_server
    server = build_server()
    r = await _call(server, "dispatch_pending", {"user_id": "u1"})
    body = json.loads(r.root.content[0].text)
    assert len(body) == 1
    assert body[0]["status"] == "sent"


@pytest.mark.asyncio
async def test_get_status(temp_notify):
    from backend.app.db import session_scope, repository as repo
    from backend.app.db.models import Notification
    async with session_scope() as s:
        await repo.upsert_user(s, "u1")
        for st in ["draft", "draft", "approved", "sent"]:
            s.add(Notification(
                user_id="u1", kind="t", title="x", body="y", status=st,
                channel="console",
            ))
        await s.flush()

    from backend.app.mcp_servers.notify.server import build_server
    server = build_server()
    r = await _call(server, "get_status", {"user_id": "u1"})
    body = json.loads(r.root.content[0].text)
    assert body["counts"]["draft"] == 2
    assert body["counts"]["approved"] == 1
    assert body["counts"]["sent"] == 1
