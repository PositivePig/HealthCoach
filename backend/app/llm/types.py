"""Common LLM types and exceptions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Role = Literal["main_chat", "vision", "router"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # OpenAI-style image parts (for vision):
    # [{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}, ...]
    image_urls: list[str] | None = None


class ChatChunk(BaseModel):
    """A streaming text delta."""

    delta: str
    finish_reason: str | None = None
    provider: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    """Non-streaming response."""

    content: str
    provider: str
    model: str
    usage: dict | None = None


class ProviderError(Exception):
    """Raised when a provider call fails. Router uses this to fall through."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
