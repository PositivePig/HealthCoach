"""LLM Router fallback tests.

Verifies the API-first + local fallback contract from ADR/0001.
"""

from __future__ import annotations

import pytest

from backend.app.llm.providers.mock import MockProvider
from backend.app.llm.router import LLMRouter
from backend.app.llm.types import ChatMessage, ProviderError


@pytest.mark.asyncio
async def test_first_provider_succeeds():
    """Happy path - first provider returns."""
    p1 = MockProvider(name="p1", succeed=True, reply="hello-from-p1")
    p2 = MockProvider(name="p2", succeed=True, reply="hello-from-p2")
    router = LLMRouter({"main_chat": [p1, p2]})

    resp = await router.chat("main_chat", [ChatMessage(role="user", content="hi")])
    assert resp.content == "hello-from-p1"
    assert resp.provider == "p1"


@pytest.mark.asyncio
async def test_falls_through_to_second_provider():
    """First provider fails → router tries the next one (the W1 core test)."""
    p1 = MockProvider(name="p1", succeed=False)
    p2 = MockProvider(name="p2", succeed=True, reply="hello-from-p2")
    router = LLMRouter({"main_chat": [p1, p2]})

    resp = await router.chat("main_chat", [ChatMessage(role="user", content="hi")])
    assert resp.content == "hello-from-p2"
    assert resp.provider == "p2"


@pytest.mark.asyncio
async def test_falls_through_multiple_providers():
    """Multi-level fallback p1 → p2 → p3."""
    p1 = MockProvider(name="p1", succeed=False)
    p2 = MockProvider(name="p2", succeed=False)
    p3 = MockProvider(name="p3", succeed=True, reply="from-p3")
    router = LLMRouter({"main_chat": [p1, p2, p3]})

    resp = await router.chat("main_chat", [ChatMessage(role="user", content="hi")])
    assert resp.provider == "p3"


@pytest.mark.asyncio
async def test_all_fail_raises():
    """All providers fail → ProviderError with retryable=False."""
    p1 = MockProvider(name="p1", succeed=False)
    p2 = MockProvider(name="p2", succeed=False)
    router = LLMRouter({"main_chat": [p1, p2]})

    with pytest.raises(ProviderError) as exc:
        await router.chat("main_chat", [ChatMessage(role="user", content="hi")])
    assert "All providers failed" in str(exc.value)


@pytest.mark.asyncio
async def test_no_provider_for_role():
    """Role not configured → ProviderError immediately."""
    router = LLMRouter({"main_chat": []})
    with pytest.raises(ProviderError) as exc:
        await router.chat("main_chat", [ChatMessage(role="user", content="hi")])
    assert "No provider configured" in str(exc.value)


@pytest.mark.asyncio
async def test_streaming_fallback():
    """Stream startup failure → falls through to next provider."""
    p1 = MockProvider(name="p1", succeed=False)
    p2 = MockProvider(name="p2", succeed=True, reply="abc")
    router = LLMRouter({"main_chat": [p1, p2]})

    gen = await router.stream("main_chat", [ChatMessage(role="user", content="hi")])
    chunks = []
    async for c in gen:
        chunks.append(c)
    text = "".join(c.delta for c in chunks)
    assert text == "abc"
    assert all(c.provider == "p2" for c in chunks)
