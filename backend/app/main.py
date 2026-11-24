"""FastAPI application entrypoint.

Run with:
    uv run uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
from .api.health import router as health_router
from .core.config import get_settings
from .core.logging import get_logger, setup_logging

# Optional imports
try:
    from .api.proactive import router as proactive_router
    HAS_PROACTIVE = True
except Exception:
    proactive_router = None
    HAS_PROACTIVE = False

try:
    from .core.langfuse_client import flush_langfuse, get_langfuse
    HAS_LANGFUSE = True
except Exception:
    flush_langfuse = lambda: None
    get_langfuse = lambda: None
    HAS_LANGFUSE = False

_scheduler: Optional[object] = None


def get_scheduler() -> Optional[object]:
    global _scheduler
    return _scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    log = get_logger("startup")
    log.info("app_starting", env=settings.app_env, storage=settings.storage_backend)

    lf = get_langfuse()
    log.info("langfuse_status", enabled=settings.langfuse_enabled, configured=bool(lf))

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from .proactive import setup_notification_service, get_job_executor
        global _scheduler
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
        log.info("scheduler_started")
        setup_notification_service(enable_console=True, enable_database=True)
        log.info("notification_service_initialized")
        get_job_executor(_scheduler)
        log.info("job_executor_initialized")
    except Exception as e:
        log.warning("proactive_skipped", reason=str(e))

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)
    flush_langfuse()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="HealthCoachAgent API",
        version="0.1.0-w7",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env == "dev" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    if proactive_router is not None:
        app.include_router(proactive_router)

    @app.get("/")
    async def root():
        return {"service": "HealthCoachAgent", "version": "0.1.0-w7", "docs": "/docs"}

    return app


app = create_app()
