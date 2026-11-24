"""Provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..types import ChatChunk, ChatMessage, ChatResponse


class BaseProvider(ABC):
    """All LLM providers implement this interface."""

    name: str = "base"
    role: str = "main_chat"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this provider is configured (has key/url)."""

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """Non-streaming chat completion."""

    @abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Streaming chat completion."""
