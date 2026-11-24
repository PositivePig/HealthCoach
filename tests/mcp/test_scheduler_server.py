"""MCP protocol tests for scheduler server.

Covers: tool listing, register/run_now/list_jobs/cancel,
HITL approve/reject state machine.
"""

from __future__ import annotations

import json

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest


@pytest.fixture
async def temp_sched(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "sched_mcp.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.db import init_db
    await init_db()

    import backend.app.scheduler.core as score
    score._core = None
    yield
    if score._core is not None:
        await score._core.shutdown()
        score._core = None
    await eng.dispose_engine()


async def _call(server, name, args):
    handler = server.request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.mark.asyncio
async def test_list_tools(temp_sched):
    from backend.app.mcp_servers.scheduler.server import build_server, TOOLS
    server = build_server()
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    names = {t.name for t in result.root.tools}
    assert names == {t.name for t in TOOLS}
    for must_have in {
        "register_job", "cancel_job", "list_jobs", "run_job_now",
        "list_job_kinds", "list_notifications",
        "approve_notification", "reject_notification",
    }:
        assert must_have in names


@pytest.mark.asyncio
async def test_register_run_then_inbox_workflow(temp_sched):
    from backend.app.mcp_servers.scheduler.server import build_server
    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    # Seed enough data so daily_report has stats
    async with session_scope() as s:
        await repo.upsert_user(s, "alice")
        await repo.add_meal(
            s, "alice", dishes=[{"name": "rice"}],
            total_kcal=200, total_protein_g=5,
        )

    server = build_server()

    # 1) list_job_kinds
    r = await _call(server, "list_job_kinds", {})
    body = json.loads(r.root.content[0].text)
    assert "daily_report" in body["job_kinds"]

    # 2) register_job
    r = await _call(server, "register_job", {
        "name": "alice-daily",
        "user_id": "alice",
        "job_kind": "daily_report",
        "cron_expr": "0 22 * * *",
        "payload": {"window_days": 1},
    })
    assert r.root.isError is False

    # 3) list_jobs
    r = await _call(server, "list_jobs", {"user_id": "alice"})
    jobs = json.loads(r.root.content[0].text)
    assert len(jobs) == 1
    assert jobs[0]["enabled"] is True

    # 4) run_job_now (no LLM key in test env → daily_report falls back to template)
    r = await _call(server, "run_job_now", {"name": "alice-daily"})
    assert json.loads(r.root.content[0].text)["fired"] is True

    # 5) list_notifications: should have 1 draft
    r = await _call(server, "list_notifications", {
        "user_id": "alice", "status": "draft",
    })
    notes = json.loads(r.root.content[0].text)
    assert len(notes) == 1
    nid = notes[0]["id"]
    assert notes[0]["status"] == "draft"
    assert "日报" in notes[0]["title"]

    # 6) HITL: approve
    r = await _call(server, "approve_notification", {"notification_id": nid})
    body = json.loads(r.root.content[0].text)
    assert body["status"] == "approved"
    assert body["decided_at"] is not None

    # 7) cannot approve again (state machine)
    r = await _call(server, "approve_notification", {"notification_id": nid})
    assert r.root.isError is True
    assert "not draft" in r.root.content[0].text


@pytest.mark.asyncio
async def test_reject_notification(temp_sched):
    from backend.app.mcp_servers.scheduler.server import build_server
    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "bob")

    server = build_server()
    await _call(server, "register_job", {
        "name": "bob-daily",
        "user_id": "bob",
        "job_kind": "daily_report",
        "interval_seconds": 3600,
    })
    await _call(server, "run_job_now", {"name": "bob-daily"})

    r = await _call(server, "list_notifications",
                    {"user_id": "bob", "status": "draft"})
    nid = json.loads(r.root.content[0].text)[0]["id"]

    r = await _call(server, "reject_notification", {
        "notification_id": nid, "reason": "tone too pushy",
    })
    body = json.loads(r.root.content[0].text)
    assert body["status"] == "rejected"
    assert body["metadata_json"].get("rejection_reason") == "tone too pushy"


@pytest.mark.asyncio
async def test_cancel_job(temp_sched):
    from backend.app.mcp_servers.scheduler.server import build_server
    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "carol")

    server = build_server()
    await _call(server, "register_job", {
        "name": "carol-job", "user_id": "carol",
        "job_kind": "daily_report", "interval_seconds": 600,
    })

    r = await _call(server, "cancel_job", {"name": "carol-job"})
    assert json.loads(r.root.content[0].text)["cancelled"] is True

    r = await _call(server, "list_jobs", {"user_id": "carol"})
    jobs = json.loads(r.root.content[0].text)
    assert len(jobs) == 1
    assert jobs[0]["enabled"] is False


@pytest.mark.asyncio
async def test_register_unknown_kind_returns_error(temp_sched):
    from backend.app.mcp_servers.scheduler.server import build_server
    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "dave")

    server = build_server()
    r = await _call(server, "register_job", {
        "name": "dave-bad",
        "user_id": "dave",
        "job_kind": "nope",
        "interval_seconds": 60,
    })
    assert r.root.isError is True
    assert "unknown job_kind" in r.root.content[0].text.lower()
