"""MCP protocol-level tests for food_vlm server.

We don't spin up actual stdio - we directly invoke the registered handlers
via the Server's internal request_handlers. This validates protocol shape
without needing a running process.
"""

from __future__ import annotations

import json

import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)

from backend.app.mcp_servers.food_vlm.server import (
    TOOL_RECOGNIZE,
    build_server,
)


@pytest.mark.asyncio
async def test_list_tools_protocol():
    """list_tools handler returns our tool with correct schema."""
    server, _ = build_server(force_mock=True)
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    tools = result.root.tools
    assert len(tools) == 1
    t = tools[0]
    assert t.name == TOOL_RECOGNIZE
    assert "image" in t.inputSchema["properties"]
    assert t.inputSchema["required"] == ["image"]
    assert t.outputSchema is not None  # schema is exposed for clients


@pytest.mark.asyncio
async def test_call_tool_recognize_food():
    """call_tool with valid args returns parseable JSON in TextContent
    AND a structuredContent matching the declared outputSchema."""
    server, _ = build_server(force_mock=True)
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name=TOOL_RECOGNIZE,
            arguments={"image": "/tmp/fake.jpg", "hint": "lunch"},
        ),
    )
    result = await handler(req)
    # Text content fallback
    contents = result.root.content
    assert len(contents) == 1
    parsed = json.loads(contents[0].text)
    assert parsed["mode"] == "mock"
    assert parsed["total_kcal"] > 0
    # Structured content (MCP 1.27 contract when outputSchema is declared)
    structured = result.root.structuredContent
    assert structured is not None
    assert structured["mode"] == "mock"
    assert structured["total_kcal"] == parsed["total_kcal"]


@pytest.mark.asyncio
async def test_call_tool_missing_image_raises():
    server, _ = build_server(force_mock=True)
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name=TOOL_RECOGNIZE,
            arguments={},
        ),
    )
    # MCP server wraps errors into a result with isError=True
    result = await handler(req)
    assert result.root.isError is True
    # Error content is a TextContent describing the failure
    text = result.root.content[0].text
    assert "image" in text.lower()


@pytest.mark.asyncio
async def test_call_tool_unknown_name_raises():
    server, _ = build_server(force_mock=True)
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="nope_not_a_tool", arguments={"image": "x"}
        ),
    )
    result = await handler(req)
    assert result.root.isError is True
