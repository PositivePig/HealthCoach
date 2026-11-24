"""OpenAI-compatible provider.

Supports DeepSeek, DashScope (Qwen), OpenAI, and any vLLM endpoint that
implements the OpenAI API contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, APIError, APIStatusError, APITimeoutError, RateLimitError

from ..types import ChatChunk, ChatMessage, ChatResponse, ProviderError
from .base import BaseProvider


def _to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Convert internal ChatMessage to OpenAI multimodal format."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.image_urls:
            parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
            for url in m.image_urls:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            out.append({"role": m.role, "content": parts})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


class OpenAICompatibleProvider(BaseProvider):
    """Generic OpenAI-compatible client.

    Different vendors share this class with different defaults.
    """

    def __init__(
        self,
        *,
        name: str,
        role: str,
        api_key: str,
        base_url: str,
        default_model: str,
    ) -> None:
        self.name = name
        self.role = role
        self._api_key = api_key
        self._base_url = base_url
        self._default_model = default_model
        self._client: AsyncOpenAI | None = None

    @property
    def available(self) -> bool:
        return bool(self._api_key) and bool(self._base_url)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.available:
                raise ProviderError(
                    f"{self.name} not configured", provider=self.name, retryable=False
                )
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        client = self._get_client()
        used_model = model or self._default_model
        try:
            resp = await client.chat.completions.create(
                model=used_model,
                messages=_to_openai_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
        except (RateLimitError, APITimeoutError) as e:
            raise ProviderError(str(e), provider=self.name, retryable=True) from e
        except APIStatusError as e:
            # 4xx: typically auth / bad request → not retryable on next provider unless 429
            retryable = e.status_code in (408, 425, 429, 500, 502, 503, 504)
            raise ProviderError(str(e), provider=self.name, retryable=retryable) from e
        except APIError as e:
            raise ProviderError(str(e), provider=self.name, retryable=True) from e
        except Exception as e:  # network etc.
            raise ProviderError(str(e), provider=self.name, retryable=True) from e

        choice = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return ChatResponse(
            content=choice, provider=self.name, model=used_model, usage=usage
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ChatChunk]:
        client = self._get_client()
        used_model = model or self._default_model
        try:
            stream = await client.chat.completions.create(
                model=used_model,
                messages=_to_openai_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        except (RateLimitError, APITimeoutError) as e:
            raise ProviderError(str(e), provider=self.name, retryable=True) from e
        except APIStatusError as e:
            retryable = e.status_code in (408, 425, 429, 500, 502, 503, 504)
            raise ProviderError(str(e), provider=self.name, retryable=retryable) from e
        except APIError as e:
            raise ProviderError(str(e), provider=self.name, retryable=True) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.name, retryable=True) from e

        async def _gen() -> AsyncIterator[ChatChunk]:
            try:
                async for event in stream:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta.content or ""
                    finish = event.choices[0].finish_reason
                    if delta or finish:
                        yield ChatChunk(
                            delta=delta,
                            finish_reason=finish,
                            provider=self.name,
                            model=used_model,
                        )
            except Exception as e:
                raise ProviderError(str(e), provider=self.name, retryable=True) from e

        return _gen()
