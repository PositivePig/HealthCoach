"""LLM routing & providers package.

API-first with local fallback strategy. See ADR/0001-model-strategy.md
"""

from .router import LLMRouter, get_router  # noqa: F401
from .types import (  # noqa: F401
    ChatChunk,
    ChatMessage,
    ChatResponse,
    ProviderError,
    Role,
)
