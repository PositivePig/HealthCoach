"""Health check."""

from fastapi import APIRouter

from ..core.config import get_settings
from ..core.langfuse_client import get_langfuse
from ..llm import get_router as get_llm_router

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    llm = get_llm_router()
    lf = get_langfuse()
    return {
        "status": "ok",
        "env": settings.app_env,
        "storage": settings.storage_backend,
        "providers": {
            role: [p.name for p in plist if p.available]
            for role, plist in llm._providers.items()  # noqa: SLF001
        },
        "langfuse": {
            "enabled": settings.langfuse_enabled,
            "configured": bool(lf),
            "host": settings.langfuse_resolved_host if lf else None,
        },
    }
