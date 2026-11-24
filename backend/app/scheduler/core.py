"""Scheduler core: APScheduler AsyncIOScheduler with self-managed persistence.

Why not use SQLAlchemyJobStore?
  APScheduler 3.x's SQLAlchemyJobStore is sync and pickles job objects, which
  doesn't compose with our async SQLAlchemy engine and our "jobs are typed
  payloads, not closures" design.

Our approach instead:
  - In-memory APScheduler (AsyncIOScheduler + MemoryJobStore) for runtime triggering
  - Our own ScheduledJob ORM table for persistence
  - On startup (or first use), reload all enabled rows into the scheduler
  - Every register/cancel goes through the DB first, then mirrors to scheduler

Trigger semantics:
  - cron_expr: standard 5-field cron ("min hour day mon dow") via CronTrigger.from_crontab
  - interval_seconds: positive int, IntervalTrigger
  - exactly one must be set
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from ..core.logging import get_logger
from ..db import session_scope
from ..db.models import ScheduledJob

log = get_logger(__name__)


# ---------- Job kind registry ----------

# A "job kind" is a coroutine function (user_id, payload) -> None.
# Registered at import time; scheduler looks up by string name.

JobFn = Callable[[str, dict[str, Any]], Awaitable[None]]
_JOB_KINDS: dict[str, JobFn] = {}


def register_job_kind(name: str):
    """Decorator: declare a coroutine function as a runnable job kind."""

    def _wrap(fn: JobFn) -> JobFn:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"job kind '{name}' must be an async function")
        _JOB_KINDS[name] = fn
        return fn

    return _wrap


def get_job_kinds() -> list[str]:
    return sorted(_JOB_KINDS)


def is_job_kind_registered(name: str) -> bool:
    return name in _JOB_KINDS


# ---------- Trigger helpers ----------


class TriggerSpecError(ValueError):
    """Invalid cron/interval input."""


def build_trigger(
    *, cron_expr: str | None, interval_seconds: int | None
) -> CronTrigger | IntervalTrigger:
    if cron_expr and interval_seconds:
        raise TriggerSpecError("set exactly one of cron_expr or interval_seconds")
    if not cron_expr and not interval_seconds:
        raise TriggerSpecError("set one of cron_expr or interval_seconds")
    if cron_expr:
        try:
            return CronTrigger.from_crontab(cron_expr)
        except Exception as e:
            raise TriggerSpecError(f"invalid cron_expr '{cron_expr}': {e}") from e
    if interval_seconds is not None and interval_seconds <= 0:
        raise TriggerSpecError("interval_seconds must be positive")
    return IntervalTrigger(seconds=int(interval_seconds))


# ---------- Core ----------


class SchedulerCore:
    """Owns the AsyncIOScheduler and syncs DB rows ↔ in-memory jobs."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._lock = asyncio.Lock()

    # ----- lifecycle -----

    async def start(self) -> None:
        async with self._lock:
            if self._scheduler is not None:
                return
            self._scheduler = AsyncIOScheduler(timezone="UTC")
            self._scheduler.start(paused=False)
            log.info("scheduler_started")
            await self._reload_from_db()

    async def shutdown(self) -> None:
        async with self._lock:
            if self._scheduler is None:
                return
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            log.info("scheduler_shutdown")

    @property
    def started(self) -> bool:
        return self._scheduler is not None

    def _ensure_started(self) -> AsyncIOScheduler:
        if self._scheduler is None:
            raise RuntimeError("scheduler not started")
        return self._scheduler

    # ----- DB ↔ scheduler sync -----

    async def _reload_from_db(self) -> None:
        async with session_scope() as session:
            stmt = select(ScheduledJob).where(ScheduledJob.enabled.is_(True))
            rows = list((await session.execute(stmt)).scalars().all())
        for row in rows:
            try:
                self._add_to_scheduler(row)
            except Exception as e:
                log.error("scheduler_reload_failed", name=row.name, error=str(e))
        log.info("scheduler_reloaded", count=len(rows))

    def _add_to_scheduler(self, row: ScheduledJob) -> None:
        """Mirror one DB row into the in-memory scheduler."""
        sched = self._ensure_started()
        if not is_job_kind_registered(row.job_kind):
            raise ValueError(f"unknown job_kind '{row.job_kind}'")
        trigger = build_trigger(
            cron_expr=row.cron_expr, interval_seconds=row.interval_seconds
        )
        # Remove first if existed
        if sched.get_job(row.name) is not None:
            sched.remove_job(row.name)
        sched.add_job(
            self._dispatch,
            trigger=trigger,
            id=row.name,
            kwargs={
                "name": row.name,
                "user_id": row.user_id,
                "job_kind": row.job_kind,
                "payload": row.payload or {},
            },
            replace_existing=True,
            misfire_grace_time=300,
        )

    @staticmethod
    async def _dispatch(name: str, user_id: str, job_kind: str, payload: dict) -> None:
        """Internal callback APScheduler invokes when a job fires."""
        log.info("job_fired", name=name, kind=job_kind, user_id=user_id)
        # Mark pending
        async with session_scope() as session:
            row = await session.get(ScheduledJob, name)
            if row is not None:
                row.last_run_at = datetime.now(tz=timezone.utc)
                row.last_run_status = "pending"
        # Run the user-defined job kind
        fn = _JOB_KINDS.get(job_kind)
        if fn is None:
            err = f"job_kind '{job_kind}' not registered"
            log.error("job_kind_missing", name=name)
            await SchedulerCore._mark_status(name, "error", err)
            return
        try:
            await fn(user_id, payload)
            await SchedulerCore._mark_status(name, "ok", None)
            log.info("job_done", name=name)
        except Exception as e:  # noqa: BLE001
            log.exception("job_error", name=name)
            await SchedulerCore._mark_status(name, "error", repr(e))

    @staticmethod
    async def _mark_status(name: str, status: str, err: str | None) -> None:
        async with session_scope() as session:
            row = await session.get(ScheduledJob, name)
            if row is not None:
                row.last_run_status = status
                row.last_run_error = err

    # ----- public api -----

    async def register(
        self,
        *,
        name: str,
        user_id: str,
        job_kind: str,
        cron_expr: str | None = None,
        interval_seconds: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        """Persist + register. If `name` already exists, replace."""
        if not is_job_kind_registered(job_kind):
            raise ValueError(
                f"unknown job_kind '{job_kind}' "
                f"(known: {get_job_kinds()})"
            )
        # Build trigger early to fail fast on bad cron
        build_trigger(cron_expr=cron_expr, interval_seconds=interval_seconds)

        async with session_scope() as session:
            existing = await session.get(ScheduledJob, name)
            if existing is None:
                existing = ScheduledJob(
                    name=name,
                    user_id=user_id,
                    job_kind=job_kind,
                    cron_expr=cron_expr,
                    interval_seconds=interval_seconds,
                    payload=payload or {},
                    enabled=True,
                )
                session.add(existing)
            else:
                existing.user_id = user_id
                existing.job_kind = job_kind
                existing.cron_expr = cron_expr
                existing.interval_seconds = interval_seconds
                existing.payload = payload or {}
                existing.enabled = True
            await session.flush()
            row = existing
            # Detach copy to return after session closes
            snapshot = ScheduledJob(
                name=row.name, user_id=row.user_id, job_kind=row.job_kind,
                cron_expr=row.cron_expr, interval_seconds=row.interval_seconds,
                payload=row.payload, enabled=row.enabled,
                last_run_at=row.last_run_at, last_run_status=row.last_run_status,
                last_run_error=row.last_run_error, created_at=row.created_at,
            )
        self._add_to_scheduler(snapshot)
        log.info("job_registered", name=name, kind=job_kind, user_id=user_id)
        return snapshot

    async def cancel(self, name: str) -> bool:
        sched = self._ensure_started()
        async with session_scope() as session:
            row = await session.get(ScheduledJob, name)
            if row is None:
                return False
            row.enabled = False
        if sched.get_job(name) is not None:
            sched.remove_job(name)
        log.info("job_cancelled", name=name)
        return True

    async def list_jobs(self, user_id: str | None = None) -> list[dict[str, Any]]:
        async with session_scope() as session:
            stmt = select(ScheduledJob)
            if user_id is not None:
                stmt = stmt.where(ScheduledJob.user_id == user_id)
            rows = list((await session.execute(stmt)).scalars().all())
            out: list[dict[str, Any]] = []
            sched = self._scheduler
            for r in rows:
                next_run = None
                if sched is not None:
                    j = sched.get_job(r.name)
                    if j is not None and j.next_run_time:
                        next_run = j.next_run_time.isoformat()
                out.append(
                    {
                        "name": r.name,
                        "user_id": r.user_id,
                        "job_kind": r.job_kind,
                        "cron_expr": r.cron_expr,
                        "interval_seconds": r.interval_seconds,
                        "payload": r.payload,
                        "enabled": r.enabled,
                        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                        "last_run_status": r.last_run_status,
                        "last_run_error": r.last_run_error,
                        "next_run_at": next_run,
                    }
                )
            return out

    async def run_now(self, name: str) -> bool:
        """Fire a job immediately, bypassing the trigger schedule.

        Useful for HITL demos and CLI smoke tests.
        """
        async with session_scope() as session:
            row = await session.get(ScheduledJob, name)
            if row is None:
                return False
            kind, user_id, payload = row.job_kind, row.user_id, row.payload or {}
        await self._dispatch(name, user_id, kind, payload)
        return True


# Module-level singleton
_core: SchedulerCore | None = None


def get_scheduler() -> SchedulerCore:
    global _core
    if _core is None:
        _core = SchedulerCore()
    return _core
