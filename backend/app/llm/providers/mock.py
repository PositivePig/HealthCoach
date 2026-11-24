"""Mock provider used in tests to simulate failures / successes deterministically."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..types import ChatChunk, ChatMessage, ChatResponse, ProviderError
from .base import BaseProvider


class MockProvider(BaseProvider):
    """Always-fails or always-succeeds provider for tests."""

    def __init__(
        self,
        *,
        name: str = "mock",
        role: str = "main_chat",
        succeed: bool = True,
        reply: str = "[mock-reply]",
        retryable_on_fail: bool = True,
    ) -> None:
        self.name = name
        self.role = role
        self._succeed = succeed
        self._reply = reply
        self._retryable_on_fail = retryable_on_fail

    @property
    def available(self) -> bool:
        return True

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        if not self._succeed:
            raise ProviderError(
                f"{self.name} simulated failure",
                provider=self.name,
                retryable=self._retryable_on_fail,
            )
        return ChatResponse(content=self._reply, provider=self.name, model="mock")

    async def stream(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        if not self._succeed:
            raise ProviderError(
                f"{self.name} simulated failure",
                provider=self.name,
                retryable=self._retryable_on_fail,
            )

        reply = self._reply
        provider = self.name

        async def _gen() -> AsyncIterator[ChatChunk]:
            for ch in reply:
                yield ChatChunk(delta=ch, provider=provider, model="mock")
            yield ChatChunk(delta="", finish_reason="stop", provider=provider, model="mock")

        return _gen()
