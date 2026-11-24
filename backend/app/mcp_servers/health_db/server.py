"""health_db MCP Server.

Exposes user-scoped health data CRUD + safe ad-hoc SELECT.

Tools (all writes are auditable via Langfuse if enabled):
  - upsert_user_profile
  - get_user_profile
  - add_meal
  - query_meals
  - aggregate_nutrition
  - add_activity
  - query_activities
  - add_vital
  - query_vitals
  - execute_safe_sql            ← READ-ONLY, whitelisted, parameterized

Run:
  uv run python -m backend.app.mcp_servers.health_db.server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.stdio import stdio_server

if __package__ is None or __package__ == "":  # pragma: no cover
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    sys.path.insert(0, repo_root)

from backend.app.core.logging import get_logger, setup_logging  # noqa: E402
from backend.app.db import init_db, session_scope  # noqa: E402
from backend.app.db import repository as repo  # noqa: E402
from backend.app.db.safe_sql import (  # noqa: E402
    UnsafeSQLError,
    execute_safe_select,
)

log = get_logger(__name__)

SERVER_NAME = "health-db"
SERVER_VERSION = "0.1.0"


def _serialize(obj: Any) -> Any:
    """Make ORM rows / datetimes JSON-friendly."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return {k: _serialize(v) for k, v in d.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ---------- tool definitions ----------


TOOLS: list[mcp_types.Tool] = [
    mcp_types.Tool(
        name="upsert_user_profile",
        title="创建/更新用户画像",
        description="语义记忆持久层：用户基本信息 + 目标 + 过敏史。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "name": {"type": "string"},
                "goal": {
                    "type": "string",
                    "enum": ["maintenance", "cut", "bulk", "longevity"],
                },
                "height_cm": {"type": "number"},
                "weight_kg": {"type": "number"},
                "target_kcal": {"type": "number"},
                "allergies": {"type": "array", "items": {"type": "string"}},
                "dislikes": {"type": "array", "items": {"type": "string"}},
                "diseases": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="get_user_profile",
        title="读取用户画像",
        description="返回用户的目标、身体数据、过敏/忌口/病史。",
        inputSchema={
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="add_meal",
        title="记录一餐",
        description=(
            "把一餐写入数据库。dishes 通常来自 food_vlm 的识别结果。"
            "可选传 ts (ISO8601) 来记录历史餐次。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "dishes": {"type": "array"},
                "total_kcal": {"type": "number"},
                "total_protein_g": {"type": "number"},
                "total_carbs_g": {"type": "number"},
                "total_fat_g": {"type": "number"},
                "total_fiber_g": {"type": "number"},
                "confidence": {"type": "number"},
                "source": {"type": "string"},
                "image_path": {"type": "string"},
                "notes": {"type": "string"},
                "ts": {"type": "string", "description": "ISO8601 datetime"},
            },
            "required": ["user_id", "dishes"],
        },
    ),
    mcp_types.Tool(
        name="query_meals",
        title="查询近 N 天餐次",
        description="按用户查询，新到旧排序，最多 100 条。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 90},
                "limit": {"type": "integer", "default": 50, "maximum": 100},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="aggregate_nutrition",
        title="汇总营养摄入",
        description="返回近 N 天的合计 + 日均（kcal/蛋白/碳水/脂肪/纤维）。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 90},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="add_activity",
        title="记录一次运动",
        description="跑步/力量/瑜伽 etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "type": {"type": "string"},
                "duration_min": {"type": "number"},
                "intensity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                },
                "hr_avg": {"type": "number"},
                "calories_burned": {"type": "number"},
                "notes": {"type": "string"},
                "ts": {"type": "string"},
            },
            "required": ["user_id", "type", "duration_min"],
        },
    ),
    mcp_types.Tool(
        name="query_activities",
        title="查询近 N 天运动",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "days": {"type": "integer", "default": 14, "minimum": 1, "maximum": 90},
                "limit": {"type": "integer", "default": 50, "maximum": 100},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="add_vital",
        title="记录体征",
        description="体重 / 体脂 / HRV / 睡眠 / 心情 中至少一项。",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "weight_kg": {"type": "number"},
                "body_fat": {"type": "number"},
                "hrv_ms": {"type": "number"},
                "sleep_min": {"type": "number"},
                "mood": {"type": "string"},
                "notes": {"type": "string"},
                "ts": {"type": "string"},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="query_vitals",
        title="查询近 N 天体征",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "days": {"type": "integer", "default": 30, "minimum": 1, "maximum": 365},
                "limit": {"type": "integer", "default": 100, "maximum": 200},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="execute_safe_sql",
        title="只读 SQL 查询（白名单）",
        description=(
            "执行 SELECT/WITH ad-hoc 查询。仅允许 meals/activities/vitals/users 表，"
            "禁止多语句 / DML / DDL，强制 LIMIT。参数请走 :name 占位符 + params 字段。"
            "调用方应保证 SQL 中至少含 user_id = :user_id 过滤条件。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "params": {
                    "type": "object",
                    "description": "Bind parameters dict, e.g. {\"user_id\": \"jason\"}",
                    "additionalProperties": True,
                },
                "limit": {
                    "type": "integer",
                    "default": 200,
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            "required": ["sql"],
        },
    ),
]


# ---------- server ----------


def build_server() -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        log.info("health_db_tool_call", tool=name, keys=sorted(arguments.keys()))

        async with session_scope() as session:
            if name == "upsert_user_profile":
                u = await repo.upsert_user(session, **arguments)
                payload = _serialize(u)

            elif name == "get_user_profile":
                u = await repo.get_user(session, arguments["user_id"])
                payload = _serialize(u) if u else None

            elif name == "add_meal":
                args = dict(arguments)
                if "ts" in args and isinstance(args["ts"], str):
                    args["ts"] = datetime.fromisoformat(args["ts"])
                m = await repo.add_meal(session, **args)
                payload = _serialize(m)

            elif name == "query_meals":
                rows = await repo.query_meals(session, **arguments)
                payload = [_serialize(r) for r in rows]

            elif name == "aggregate_nutrition":
                payload = await repo.aggregate_nutrition(session, **arguments)

            elif name == "add_activity":
                args = dict(arguments)
                if "ts" in args and isinstance(args["ts"], str):
                    args["ts"] = datetime.fromisoformat(args["ts"])
                a = await repo.add_activity(session, **args)
                payload = _serialize(a)

            elif name == "query_activities":
                rows = await repo.query_activities(session, **arguments)
                payload = [_serialize(r) for r in rows]

            elif name == "add_vital":
                args = dict(arguments)
                if "ts" in args and isinstance(args["ts"], str):
                    args["ts"] = datetime.fromisoformat(args["ts"])
                v = await repo.add_vital(session, **args)
                payload = _serialize(v)

            elif name == "query_vitals":
                rows = await repo.query_vitals(session, **arguments)
                payload = [_serialize(r) for r in rows]

            elif name == "execute_safe_sql":
                try:
                    payload = await execute_safe_select(
                        session,
                        arguments["sql"],
                        params=arguments.get("params"),
                        limit=arguments.get("limit", 200),
                    )
                except UnsafeSQLError as e:
                    raise ValueError(f"unsafe sql rejected: {e}") from e

            else:
                raise ValueError(f"Unknown tool: {name}")

        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return [mcp_types.TextContent(type="text", text=text)]

    return server


# ---------- entry ----------


async def _run_stdio() -> None:
    # Ensure tables exist (dev convenience; production uses alembic)
    await init_db()
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="health-db-mcp")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    setup_logging(args.log_level, stream=sys.stderr)
    log.info("health_db_server_starting", version=SERVER_VERSION)
    try:
        asyncio.run(_run_stdio())
    except KeyboardInterrupt:
        log.info("health_db_server_stopped")


if __name__ == "__main__":
    main()
