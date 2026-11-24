"""SQLAlchemy async engine + session factory.

Engine is lazily created on first call (cheap, side-effect free at import).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import get_settings
from ..core.logging import get_logger
from .models import Base

log = get_logger(__name__)

_engine = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    """Get (or create) the async engine."""
    global _engine, AsyncSessionLocal
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.db_url

    # Ensure SQLite directory exists
    if url.startswith("sqlite"):
        # url like: sqlite+aiosqlite:///./data/healthcoach.db
        path_part = url.split(":///", 1)[1]
        if path_part and not path_part.startswith(":memory:"):
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )
    AsyncSessionLocal = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    log.info("db_engine_created", url=url.split("@")[-1] if "@" in url else url)
    return _engine


async def init_db() -> None:
    """Create all tables (dev convenience). Production uses alembic."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("db_tables_created", tables=list(Base.metadata.tables.keys()))


async def dispose_engine() -> None:
    global _engine, AsyncSessionLocal
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        AsyncSessionLocal = None


@asynccontextmanager
async def session_scope():
    """Yield an async session; commit on success, rollback on error."""
    if AsyncSessionLocal is None:
        get_engine()  # initializes the factory

    assert AsyncSessionLocal is not None
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
