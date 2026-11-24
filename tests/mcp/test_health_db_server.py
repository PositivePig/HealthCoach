"""MCP protocol tests for health_db server.

Verifies list_tools count + a few critical call_tool flows:
  - upsert_user_profile + get_user_profile roundtrip
  - add_meal + query_meals + aggregate_nutrition
  - execute_safe_sql happy + rejection paths
"""

from __future__ import annotations

import json

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest


@pytest.fixture
async def temp_health_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "mcp.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.db import init_db
    await init_db()
    yield
    await eng.dispose_engine()


def _call_handler(server):
    return server.request_handlers[CallToolRequest]


async def _call(server, name, args):
    handler = _call_handler(server)
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.mark.asyncio
async def test_list_tools_has_all(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server, TOOLS
    server = build_server()
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    names = [t.name for t in result.root.tools]
    assert len(names) == len(TOOLS)
    for expected in [
        "upsert_user_profile", "get_user_profile",
        "add_meal", "query_meals", "aggregate_nutrition",
        "add_activity", "query_activities",
        "add_vital", "query_vitals",
        "execute_safe_sql",
    ]:
        assert expected in names


@pytest.mark.asyncio
async def test_user_profile_roundtrip(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server
    server = build_server()

    r1 = await _call(server, "upsert_user_profile", {
        "user_id": "alice", "name": "Alice", "goal": "cut",
        "allergies": ["peanut"], "target_kcal": 1600,
    })
    assert r1.root.isError is False

    r2 = await _call(server, "get_user_profile", {"user_id": "alice"})
    body = json.loads(r2.root.content[0].text)
    assert body["id"] == "alice"
    assert body["goal"] == "cut"
    assert "peanut" in body["allergies"]


@pytest.mark.asyncio
async def test_meal_flow(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server
    server = build_server()

    await _call(server, "upsert_user_profile", {"user_id": "bob"})
    await _call(server, "add_meal", {
        "user_id": "bob",
        "dishes": [{"name": "noodles", "kcal": 500, "protein_g": 15,
                    "carbs_g": 80, "fat_g": 12}],
        "total_kcal": 500, "total_protein_g": 15,
        "total_carbs_g": 80, "total_fat_g": 12,
        "confidence": 0.8, "source": "photo",
    })

    r = await _call(server, "query_meals", {"user_id": "bob", "days": 7})
    meals = json.loads(r.root.content[0].text)
    assert len(meals) == 1
    assert meals[0]["total_kcal"] == 500

    r = await _call(server, "aggregate_nutrition",
                    {"user_id": "bob", "days": 7})
    agg = json.loads(r.root.content[0].text)
    assert agg["total_kcal"] == 500.0
    assert agg["meal_count"] == 1


@pytest.mark.asyncio
async def test_safe_sql_happy_path(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server
    server = build_server()

    await _call(server, "upsert_user_profile", {"user_id": "carol"})
    await _call(server, "add_meal", {
        "user_id": "carol", "dishes": [{"name": "x"}], "total_kcal": 100,
    })

    r = await _call(server, "execute_safe_sql", {
        "sql": "SELECT user_id, total_kcal FROM meals WHERE user_id = :uid",
        "params": {"uid": "carol"},
    })
    rows = json.loads(r.root.content[0].text)
    assert len(rows) == 1 and rows[0]["user_id"] == "carol"


@pytest.mark.asyncio
async def test_safe_sql_rejects_dml(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server
    server = build_server()

    r = await _call(server, "execute_safe_sql", {
        "sql": "DELETE FROM meals WHERE user_id = :uid",
        "params": {"uid": "anyone"},
    })
    # MCP server wraps errors into isError + text content
    assert r.root.isError is True
    assert "unsafe sql" in r.root.content[0].text.lower()


@pytest.mark.asyncio
async def test_safe_sql_rejects_off_whitelist_table(temp_health_db):
    from backend.app.mcp_servers.health_db.server import build_server
    server = build_server()

    r = await _call(server, "execute_safe_sql", {
        "sql": "SELECT * FROM sqlite_master",
    })
    assert r.root.isError is True
    text = r.root.content[0].text.lower()
    assert "whitelist" in text or "not in whitelist" in text or "unsafe" in text
