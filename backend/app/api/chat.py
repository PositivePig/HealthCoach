"""Chat routes - SSE streaming + non-stream."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..agents.hello_graph import get_hello_graph, stream_hello
from ..core.logging import get_logger
from ..llm.types import ProviderError

router = APIRouter(prefix="/chat", tags=["chat"])
log = get_logger(__name__)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    provider: str
    model: str


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming hello-world chat (runs through LangGraph)."""
    graph = get_hello_graph()
    try:
        out = await graph.ainvoke({"user_input": req.message})
    except ProviderError as e:
        log.error("chat_failed", error=str(e))
        return ChatResponse(
            response=f"[error] all providers failed: {e}",
            provider="none",
            model="none",
        )
    return ChatResponse(
        response=out.get("response", ""),
        provider=out.get("provider", ""),
        model=out.get("model", ""),
    )


@router.get("/stream")
async def chat_stream(message: str = "你好"):
    """SSE streaming endpoint. Frontend reads via EventSource.

    Each event is JSON: {"delta": "...", "provider": "...", "done": false}
    """

    async def event_gen():
        try:
            async for chunk in stream_hello(message):
                payload = {
                    "delta": chunk.delta,
                    "provider": chunk.provider,
                    "model": chunk.model,
                    "done": chunk.finish_reason is not None,
                }
                yield {"event": "message", "data": json.dumps(payload, ensure_ascii=False)}
            yield {"event": "done", "data": "{}"}
        except ProviderError as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())
