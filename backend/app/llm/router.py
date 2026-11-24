"""LLM Router: API-first with local fallback.

Each role has an ordered provider list. On failure, the router falls through
to the next provider. See ADR/0001-model-strategy.md
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from .providers import BaseProvider, OpenAICompatibleProvider
from .types import ChatChunk, ChatMessage, ChatResponse, ProviderError, Role

log = get_logger(__name__)


class LLMRouter:
    """Routes LLM calls by role with automatic failover."""

    def __init__(self, providers: dict[Role, list[BaseProvider]]) -> None:
        self._providers = providers

    def list_providers(self, role: Role) -> list[BaseProvider]:
        return self._providers.get(role, [])

    def _available(self, role: Role) -> list[BaseProvider]:
        avail = [p for p in self._providers.get(role, []) if p.available]
        if not avail:
            raise ProviderError(
                f"No provider configured for role={role}", retryable=False
            )
        return avail

    async def chat(
        self,
        role: Role,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        last_err: Exception | None = None
        for p in self._available(role):
            try:
                resp = await p.chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                log.info("llm_call_ok", role=role, provider=p.name, model=resp.model)
                return resp
            except ProviderError as e:
                last_err = e
                log.warning(
                    "llm_provider_failed",
                    role=role,
                    provider=p.name,
                    error=str(e),
                    retryable=e.retryable,
                )
                if not e.retryable:
                    # Non-retryable (e.g., 401 auth): still try next provider,
                    # because we want resilience across vendors.
                    continue
                continue
        raise ProviderError(
            f"All providers failed for role={role}: {last_err}", retryable=False
        ) from last_err

    async def stream(
        self,
        role: Role,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Stream from first working provider.

        Note: streams are unidirectional once started. We try to *start* the
        stream from each provider in order; if startup fails we fall through.
        Once chunks begin flowing, an in-flight failure aborts (we don't
        switch mid-stream).
        """
        last_err: Exception | None = None
        for p in self._available(role):
            try:
                gen = await p.stream(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                log.info("llm_stream_started", role=role, provider=p.name)
                return gen  # successful start
            except ProviderError as e:
                last_err = e
                log.warning(
                    "llm_stream_start_failed",
                    role=role,
                    provider=p.name,
                    error=str(e),
                )
                continue
        raise ProviderError(
            f"All providers failed to start stream for role={role}: {last_err}",
            retryable=False,
        ) from last_err


# ---------------------------------------------------------------------------
# Default router built from settings
# ---------------------------------------------------------------------------


def _build_default_providers(settings: Settings) -> dict[Role, list[BaseProvider]]:
    """Build the default routing table from settings.

    Order = preference. Unavailable providers (no key) are kept in the list
    but filtered out at call time, so adding a key flips them on without
    code changes.
    """
    # main_chat: DeepSeek → Anthropic (TODO) → Local vLLM
    deepseek = OpenAICompatibleProvider(
        name="deepseek",
        role="main_chat",
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        default_model=settings.deepseek_main_model,
    )
    qwen_text = OpenAICompatibleProvider(
        name="qwen-text",
        role="main_chat",
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        default_model=settings.dashscope_text_model,
    )
    local_text = OpenAICompatibleProvider(
        name="local-llm",
        role="main_chat",
        api_key="EMPTY",  # vLLM doesn't require a real key
        base_url=settings.local_llm_base_url,
        default_model=settings.local_llm_model,
    )

    # vision: Qwen-VL → OpenAI GPT-4o → Local VL
    qwen_vl = OpenAICompatibleProvider(
        name="qwen-vl",
        role="vision",
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        default_model=settings.dashscope_vl_model,
    )
    openai_vl = OpenAICompatibleProvider(
        name="openai-vl",
        role="vision",
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        default_model=settings.openai_vl_model,
    )
    local_vl = OpenAICompatibleProvider(
        name="local-vl",
        role="vision",
        api_key="EMPTY",
        base_url=settings.local_vl_base_url,
        default_model=settings.local_vl_model,
    )

    # router (cheap classification): DeepSeek → Qwen text → local
    return {
        "main_chat": [deepseek, qwen_text, local_text],
        "vision": [qwen_vl, openai_vl, local_vl],
        "router": [deepseek, qwen_text, local_text],
    }


@lru_cache
def get_router() -> LLMRouter:
    settings = get_settings()
    providers = _build_default_providers(settings)
    log.info(
        "router_initialized",
        roles={role: [p.name for p in plist] for role, plist in providers.items()},
        available={
            role: [p.name for p in plist if p.available]
            for role, plist in providers.items()
        },
    )
    return LLMRouter(providers)
