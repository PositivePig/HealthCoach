"""LangGraph hello-world tests using mocked router."""

from __future__ import annotations

import pytest

from backend.app.agents.hello_graph import HelloState, build_hello_graph
from backend.app.llm.providers.mock import MockProvider
from backend.app.llm.router import LLMRouter


@pytest.mark.asyncio
async def test_hello_graph_runs(monkeypatch):
    """Run the LangGraph end-to-end with a mock LLM."""
    mock_router = LLMRouter(
        {"main_chat": [MockProvider(succeed=True, reply="hi! [W1-hello-world]")]}
    )

    # Patch get_router used inside hello_graph
    import backend.app.agents.hello_graph as hg

    monkeypatch.setattr(hg, "get_router", lambda: mock_router)

    graph = build_hello_graph()
    out: HelloState = await graph.ainvoke({"user_input": "hello"})
    assert out["response"].startswith("hi!")
    assert out["provider"] == "mock"
