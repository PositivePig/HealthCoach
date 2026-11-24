"""food_vlm MCP Server.

Single-purpose MCP server that exposes food image recognition as a tool.
Conforms to MCP 1.27.x SDK.

Run as:
  python -m backend.app.mcp_servers.food_vlm.server          # stdio
  python -m backend.app.mcp_servers.food_vlm.server --help   # CLI

Tool exposed:
  recognize_food(image_b64|image_path|image_url, hint?) -> RecognizeFoodResult JSON

The agent (or any MCP client like Claude Desktop) can list & call this tool.
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

# Ensure parent app package is importable when running as `python path/to/server.py`
# (when running with -m, this is automatic)
if __package__ is None or __package__ == "":  # pragma: no cover
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    sys.path.insert(0, repo_root)

from backend.app.core.logging import get_logger, setup_logging  # noqa: E402
from backend.app.mcp_servers.food_vlm.recognizer import FoodRecognizer  # noqa: E402
from backend.app.mcp_servers.food_vlm.schema import RecognizeFoodResult  # noqa: E402

log = get_logger(__name__)

SERVER_NAME = "food-vlm"
SERVER_VERSION = "0.1.0"

TOOL_RECOGNIZE = "recognize_food"

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image": {
            "type": "string",
            "description": (
                "图片来源，支持: (a) 本地路径 e.g. /tmp/meal.jpg, "
                "(b) 原始 base64 字符串, "
                "(c) 已格式化的 data URL e.g. data:image/jpeg;base64,xxxx, "
                "(d) http(s) 公网 URL"
            ),
        },
        "hint": {
            "type": "string",
            "description": "可选：用户对菜品的文字提示（例如：这是减脂餐 / 是麻辣香锅）",
        },
    },
    "required": ["image"],
}

OUTPUT_SCHEMA: dict[str, Any] = RecognizeFoodResult.model_json_schema()


# ---------------------------- Server ----------------------------


def build_server(*, force_mock: bool = False) -> tuple[Server, FoodRecognizer]:
    """Construct an MCP Server with our tool registered."""
    server: Server = Server(SERVER_NAME)
    recognizer = FoodRecognizer(force_mock=force_mock)

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=TOOL_RECOGNIZE,
                title="识别食物并估算营养",
                description=(
                    "识别图片中的食物并返回结构化营养信息（热量/蛋白/碳水/脂肪/纤维 + 置信度）。"
                    "使用 Qwen-VL 视觉模型。"
                ),
                inputSchema=INPUT_SCHEMA,
                outputSchema=OUTPUT_SCHEMA,
            )
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> tuple[list[mcp_types.TextContent], dict[str, Any]]:
        """Return (unstructured_content, structured_content).

        MCP 1.27 requires structured output when outputSchema is declared,
        and we also return a human-readable JSON text fallback for clients
        (or older agents) that prefer plain text.
        """
        if name != TOOL_RECOGNIZE:
            raise ValueError(f"Unknown tool: {name}")

        image = arguments.get("image", "")
        if not image:
            raise ValueError("`image` argument is required")
        hint = arguments.get("hint")

        log.info("food_vlm_tool_call", tool=name, has_hint=bool(hint))
        result = await recognizer.recognize(image, hint)
        structured = result.model_dump()
        text_repr = json.dumps(structured, ensure_ascii=False, indent=2)
        return [mcp_types.TextContent(type="text", text=text_repr)], structured

    return server, recognizer


# ---------------------------- Entry point ----------------------------


async def _run_stdio(force_mock: bool) -> None:
    server, _ = build_server(force_mock=force_mock)
    async with stdio_server() as (read, write):
        # Newer MCP SDKs require initialization options
        init_opts = server.create_initialization_options()
        await server.run(read, write, init_opts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="food-vlm-mcp",
        description="MCP server: food image recognition (Qwen-VL backed).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force mock mode (no API calls). Useful for offline testing.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO; respects $LOG_LEVEL).",
    )
    args = parser.parse_args(argv)

    # MCP stdio: stdout is reserved for JSON-RPC. All logs must go to stderr.
    setup_logging(args.log_level, stream=sys.stderr)

    log.info(
        "food_vlm_server_starting",
        version=SERVER_VERSION,
        mock=args.mock,
    )
    try:
        asyncio.run(_run_stdio(force_mock=args.mock))
    except KeyboardInterrupt:
        log.info("food_vlm_server_stopped")


if __name__ == "__main__":
    main()
