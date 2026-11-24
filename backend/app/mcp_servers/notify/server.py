"""notify MCP Server.

Tools:
  - list_channels         enumerate channels + availability
  - dispatch_pending      send all approved notifications (optionally per user)
  - dispatch_one          send one notification by id
  - test_channel          send a synthetic message via a channel (dry run)
  - get_status            quick stats: counts by status

The actual delivery and retry are in backend/app/notify/dispatcher.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from sqlalchemy import func, select

if __package__ is None or __package__ == "":  # pragma: no cover
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    sys.path.insert(0, repo_root)

from backend.app.core.logging import get_logger, setup_logging  # noqa: E402
from backend.app.db import init_db, session_scope  # noqa: E402
from backend.app.db.models import Notification  # noqa: E402
from backend.app.notify import (  # noqa: E402
    ChannelError,
    dispatch_one,
    dispatch_pending,
    get_channel,
    list_channels,
)

log = get_logger(__name__)

SERVER_NAME = "notify"
SERVER_VERSION = "0.1.0"


TOOLS: list[mcp_types.Tool] = [
    mcp_types.Tool(
        name="list_channels",
        title="列出可用投递渠道",
        description="返回 console / file / email 等渠道及其可用性。",
        inputSchema={"type": "object", "properties": {}},
    ),
    mcp_types.Tool(
        name="dispatch_pending",
        title="批量投递所有已批准的通知",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "可选；不传则跨用户"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        },
    ),
    mcp_types.Tool(
        name="dispatch_one",
        title="单条投递",
        inputSchema={
            "type": "object",
            "properties": {"notification_id": {"type": "integer"}},
            "required": ["notification_id"],
        },
    ),
    mcp_types.Tool(
        name="test_channel",
        title="试投：用合成消息测试一个 channel（不入库）",
        inputSchema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["console", "file", "email"]},
                "user_id": {"type": "string", "default": "test-user"},
                "title": {"type": "string", "default": "(test) hello"},
                "body": {"type": "string", "default": "这是一条 channel 测试消息。"},
            },
            "required": ["channel"],
        },
    ),
    mcp_types.Tool(
        name="get_status",
        title="返回 notifications 表的状态计数",
        inputSchema={
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
        },
    ),
]


def build_server() -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return TOOLS

    @server.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        log.info("notify_tool_call", tool=name, keys=sorted(args.keys()))

        if name == "list_channels":
            payload = list_channels()

        elif name == "dispatch_pending":
            payload = await dispatch_pending(
                user_id=args.get("user_id"),
                limit=int(args.get("limit", 50)),
            )

        elif name == "dispatch_one":
            payload = await dispatch_one(int(args["notification_id"]))

        elif name == "test_channel":
            channel_name = args["channel"]
            try:
                ch = get_channel(channel_name)
                if not ch.available:
                    raise ChannelError(f"channel '{channel_name}' is not configured")
                audit = await ch.send(
                    user_id=args.get("user_id", "test-user"),
                    title=args.get("title", "(test) hello"),
                    body=args.get("body", "这是一条 channel 测试消息。"),
                    metadata={"test": True},
                )
                payload = {"ok": True, "audit": audit}
            except ChannelError as e:
                payload = {"ok": False, "error": str(e)}

        elif name == "get_status":
            user_id = args.get("user_id")
            async with session_scope() as session:
                stmt = select(Notification.status, func.count(Notification.id)).group_by(
                    Notification.status
                )
                if user_id is not None:
                    stmt = stmt.where(Notification.user_id == user_id)
                rows = (await session.execute(stmt)).all()
                payload = {
                    "user_id": user_id,
                    "counts": {status: int(n) for status, n in rows},
                }

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
    parser = argparse.ArgumentParser(prog="notify-mcp")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    setup_logging(args.log_level, stream=sys.stderr)
    log.info("notify_server_starting", version=SERVER_VERSION)
    try:
        asyncio.run(_run_stdio())
    except KeyboardInterrupt:
        log.info("notify_server_stopped")


if __name__ == "__main__":
    main()
