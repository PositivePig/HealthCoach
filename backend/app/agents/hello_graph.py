"""LangGraph hello-world: a single-node agent that echoes via LLM.

Demonstrates state, nodes, streaming, and Langfuse trace hookup.
This is the W1 minimum—real Supervisor/Coach come in W3+.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..core.langfuse_client import get_langfuse
from ..core.logging import get_logger
from ..llm import ChatMessage, get_router
from ..llm.types import ChatChunk

log = get_logger(__name__)


class HelloState(TypedDict, total=False):
    user_input: str
    response: str
    provider: str
    model: str


def _system_prompt() -> str:
    return (
        "你是 HealthCoachAgent 的 hello-world 节点。"
        "用 1-2 句话友好地回应用户，并在结尾标注 [W1-hello-world]。"
    )


async def echo_node(state: HelloState) -> HelloState:
    """Single LLM-backed node. Wraps call in a Langfuse span if enabled."""
    user_input = state.get("user_input", "")
    router = get_router()
    lf = get_langfuse()

    messages = [
        ChatMessage(role="system", content=_system_prompt()),
        ChatMessage(role="user", content=user_input or "你好"),
    ]

    if lf is not None:
        # W1: wrap in a generation observation so we can see it in the UI.
        with lf.start_as_current_observation(name="echo_node", as_type="generation") as gen:
            gen.update(input=[m.model_dump() for m in messages])
            resp = await router.chat(
                "main_chat", messages, temperature=0.3, max_tokens=200
            )
            gen.update(
                output=resp.content,
                model=resp.model,
                metadata={"provider": resp.provider, "usage": resp.usage},
            )
    else:
        resp = await router.chat("main_chat", messages, temperature=0.3, max_tokens=200)

    return {
        "response": resp.content,
        "provider": resp.provider,
        "model": resp.model,
    }


def build_hello_graph():
    """Compile a single-node graph: START → echo → END."""
    g: StateGraph = StateGraph(HelloState)
    g.add_node("echo", echo_node)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile()


# Singleton compiled graph
_graph = None


def get_hello_graph():
    global _graph
    if _graph is None:
        _graph = build_hello_graph()
    return _graph


# ----------------------------- Streaming helper -----------------------------


async def stream_hello(user_input: str) -> AsyncIterator[ChatChunk]:
    """Stream tokens directly from the LLM router (bypassing graph compile,
    since W1 graph has only one LLM node anyway).

    Real graphs in W3+ will stream node-by-node via graph.astream_events().
    """
    router = get_router()
    lf = get_langfuse()
    messages = [
        ChatMessage(role="system", content=_system_prompt()),
        ChatMessage(role="user", content=user_input or "你好"),
    ]

    if lf is not None:
        with lf.start_as_current_observation(name="stream_hello", as_type="generation") as gen:
            gen.update(input=[m.model_dump() for m in messages])
            collected: list[str] = []
            collected_provider = ""
            collected_model = ""
            stream = await router.stream(
                "main_chat", messages, temperature=0.3, max_tokens=300
            )
            async for chunk in stream:
                collected.append(chunk.delta)
                if chunk.provider:
                    collected_provider = chunk.provider
                if chunk.model:
                    collected_model = chunk.model
                yield chunk
            gen.update(
                output="".join(collected),
                model=collected_model,
                metadata={"provider": collected_provider},
            )
    else:
        stream = await router.stream("main_chat", messages, temperature=0.3, max_tokens=300)
        async for chunk in stream:
            yield chunk
