"""scheduler MCP Server.

Exposes scheduling primitives + HITL notification approval as tools.

Tools:
  - register_job          create/update a scheduled job
  - cancel_job            disable & remove a job
  - list_jobs             list jobs (optionally filtered by user)
  - run_job_now           fire immediately, ignoring schedule
  - list_job_kinds        what job_kind values are accepted
  - list_notifications    inbox: drafts/approved/sent for a user
  - approve_notification  HITL: draft → approved
  - reject_notification   HITL: draft → rejected
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from sqlalchemy import select

if __package__ is None or __package__ == "":  # pragma: no cover
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    sys.path.insert(0, repo_root)

from backend.app.core.logging import get_logger, setup_logging  # noqa: E402
from backend.app.db import init_db, session_scope  # noqa: E402
from backend.app.db.models import Notification  # noqa: E402
from backend.app.scheduler import (  # noqa: E402
    get_job_kinds,
    get_scheduler,
)

log = get_logger(__name__)

SERVER_NAME = "scheduler"
SERVER_VERSION = "0.1.0"


TOOLS: list[mcp_types.Tool] = [
    mcp_types.Tool(
        name="register_job",
        title="注册/更新一个定时任务",
        description=(
            "为指定用户注册一个 job_kind 触发器。"
            "cron_expr 与 interval_seconds 二选一。"
            "已存在同名任务会被替换。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "user_id": {"type": "string"},
                "job_kind": {"type": "string"},
                "cron_expr": {"type": "string", "description": "5 字段 cron，如 '0 22 * * *'"},
                "interval_seconds": {"type": "integer", "minimum": 1},
                "payload": {"type": "object", "additionalProperties": True},
            },
            "required": ["name", "user_id", "job_kind"],
        },
    ),
    mcp_types.Tool(
        name="cancel_job",
        title="取消一个定时任务",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    mcp_types.Tool(
        name="list_jobs",
        title="列出定时任务",
        inputSchema={
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
        },
    ),
    mcp_types.Tool(
        name="run_job_now",
        title="立即执行一次（不等下次触发）",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    mcp_types.Tool(
        name="list_job_kinds",
        title="列出已注册的 job_kind",
        inputSchema={"type": "object", "properties": {}},
    ),
    mcp_types.Tool(
        name="list_notifications",
        title="列出用户的通知（按 status 过滤）",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["draft", "approved", "rejected", "sent", "failed"],
                },
                "limit": {"type": "integer", "default": 50, "maximum": 200},
            },
            "required": ["user_id"],
        },
    ),
    mcp_types.Tool(
        name="approve_notification",
        title="HITL：批准草稿",
        description="把通知 draft → approved，可选指定投递 channel。notify MCP 会拾取并发送。",
        inputSchema={
            "type": "object",
            "properties": {
                "notification_id": {"type": "integer"},
                "channel": {
                    "type": "string",
                    "enum": ["console", "file", "email"],
                    "default": "console",
                },
            },
            "required": ["notification_id"],
        },
    ),
    mcp_types.Tool(
        name="reject_notification",
        title="HITL：拒绝草稿",
        inputSchema={
            "type": "object",
            "properties": {
                "notification_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["notification_id"],
        },
    ),
]


def _serialize_notification(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "metadata_json": n.metadata_json,
        "status": n.status,
        "channel": n.channel,
        "delivery_attempts": n.delivery_attempts,
        "delivery_error": n.delivery_error,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "decided_at": n.decided_at.isoformat() if n.decided_at else None,
        "sent_at": n.sent_at.isoformat() if n.sent_at else None,
    }


def build_server() -> Server:
    server: Server = Server(SERVER_NAME)
    sched = get_scheduler()

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        log.info("scheduler_tool_call", tool=name, keys=sorted(args.keys()))

        # Lazily start scheduler on first call
        if not sched.started:
            await sched.start()

        if name == "register_job":
            row = await sched.register(
                name=args["name"],
                user_id=args["user_id"],
                job_kind=args["job_kind"],
                cron_expr=args.get("cron_expr"),
                interval_seconds=args.get("interval_seconds"),
                payload=args.get("payload") or {},
            )
            payload = {
                "name": row.name,
                "user_id": row.user_id,
                "job_kind": row.job_kind,
                "cron_expr": row.cron_expr,
                "interval_seconds": row.interval_seconds,
                "payload": row.payload,
                "enabled": row.enabled,
            }

        elif name == "cancel_job":
            ok = await sched.cancel(args["name"])
            payload = {"name": args["name"], "cancelled": ok}

        elif name == "list_jobs":
            payload = await sched.list_jobs(args.get("user_id"))

        elif name == "run_job_now":
            ok = await sched.run_now(args["name"])
            payload = {"name": args["name"], "fired": ok}

        elif name == "list_job_kinds":
            payload = {"job_kinds": get_job_kinds()}

        elif name == "list_notifications":
            user_id = args["user_id"]
            status = args.get("status")
            limit = int(args.get("limit", 50))
            async with session_scope() as session:
                stmt = select(Notification).where(Notification.user_id == user_id)
                if status:
                    stmt = stmt.where(Notification.status == status)
                stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
                rows = list((await session.execute(stmt)).scalars().all())
                payload = [_serialize_notification(r) for r in rows]

        elif name == "approve_notification":
            nid = int(args["notification_id"])
            channel = args.get("channel", "console")
            async with session_scope() as session:
                row = await session.get(Notification, nid)
                if row is None:
                    raise ValueError(f"notification {nid} not found")
                if row.status != "draft":
                    raise ValueError(f"notification {nid} is not draft (status={row.status})")
                row.status = "approved"
                row.channel = channel
                row.decided_at = datetime.now(tz=timezone.utc)
                payload = _serialize_notification(row)

        elif name == "reject_notification":
            nid = int(args["notification_id"])
            reason = args.get("reason", "")
            async with session_scope() as session:
                row = await session.get(Notification, nid)
                if row is None:
                    raise ValueError(f"notification {nid} not found")
                if row.status != "draft":
                    raise ValueError(f"notification {nid} is not draft (status={row.status})")
                row.status = "rejected"
                row.decided_at = datetime.now(tz=timezone.utc)
                if reason:
                    row.metadata_json = {**(row.metadata_json or {}), "rejection_reason": reason}
                payload = _serialize_notification(row)

        else:
            raise ValueError(f"Unknown tool: {name}")

        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return [mcp_types.TextContent(type="text", text=text)]

    return server


# ---------- entry ----------


async def _run_stdio() -> None:
    await init_db()
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scheduler-mcp")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    setup_logging(args.log_level, stream=sys.stderr)
    log.info("scheduler_server_starting", version=SERVER_VERSION)
    try:
        asyncio.run(_run_stdio())
    except KeyboardInterrupt:
        log.info("scheduler_server_stopped")


if __name__ == "__main__":
    main()
