"""Langfuse observability glue (compatible with langfuse>=3.x OTel-based SDK).

Usage:
    from .langfuse_client import get_langfuse, traced_generation

    lf = get_langfuse()
    if lf:
        with lf.start_as_current_observation(name="my-op", as_type="span") as span:
            span.update(input={"foo": "bar"})
            ...
            span.update(output={"result": "..."})

For LLM calls specifically, use start_as_current_observation(as_type="generation").
"""

from __future__ import annotations

from typing import Any

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)

_langfuse_client: Any = None
_init_attempted = False


def get_langfuse() -> Any:
    """Return a Langfuse client or None if disabled / not configured.

    Lazy-initialized singleton. Safe to call repeatedly.
    """
    global _langfuse_client, _init_attempted
    if _init_attempted:
        return _langfuse_client
    _init_attempted = True

    settings = get_settings()
    if not settings.langfuse_enabled:
        log.info("langfuse_disabled_by_config")
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        log.warning("langfuse_disabled_missing_keys")
        return None

    host = settings.langfuse_resolved_host
    try:
        from langfuse import Langfuse

        # langfuse 3.x/4.x accepts both `host` and `base_url`. Use `host`.
        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=host,
        )
        log.info("langfuse_initialized", host=host)
        return _langfuse_client
    except Exception as e:  # pragma: no cover
        log.error("langfuse_init_failed", error=str(e))
        return None


def flush_langfuse() -> None:
    """Force-flush pending events. Call on shutdown."""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception as e:  # pragma: no cover
            log.warning("langfuse_flush_failed", error=str(e))
