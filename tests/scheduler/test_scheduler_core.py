"""Scheduler core unit tests.

These don't actually wait for cron to fire (would be flaky); instead we:
  - validate trigger building
  - exercise the persistence + run_now path (which dispatches synchronously)
  - verify draft notification HITL state machine
"""

from __future__ import annotations

import pytest

from backend.app.scheduler import (
    TriggerSpecError,
    build_trigger,
    get_job_kinds,
    get_scheduler,
    is_job_kind_registered,
)


# ---------- triggers ----------


def test_build_trigger_cron_ok():
    trig = build_trigger(cron_expr="0 22 * * *", interval_seconds=None)
    assert "cron" in repr(trig).lower()


def test_build_trigger_interval_ok():
    trig = build_trigger(cron_expr=None, interval_seconds=60)
    assert "interval" in repr(trig).lower()


def test_build_trigger_both_set_rejected():
    with pytest.raises(TriggerSpecError):
        build_trigger(cron_expr="0 22 * * *", interval_seconds=60)


def test_build_trigger_neither_set_rejected():
    with pytest.raises(TriggerSpecError):
        build_trigger(cron_expr=None, interval_seconds=None)


def test_build_trigger_bad_cron():
    with pytest.raises(TriggerSpecError):
        build_trigger(cron_expr="not a cron", interval_seconds=None)


def test_build_trigger_bad_interval():
    with pytest.raises(TriggerSpecError):
        build_trigger(cron_expr=None, interval_seconds=0)


# ---------- registry ----------


def test_builtin_job_kinds_registered():
    kinds = get_job_kinds()
    assert "daily_report" in kinds
    assert "protein_low_alert" in kinds
    assert is_job_kind_registered("daily_report")
    assert not is_job_kind_registered("does_not_exist")


# ---------- core lifecycle + run_now ----------


@pytest.fixture
async def temp_db_and_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "sched.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.db import init_db
    await init_db()

    # Reset singleton scheduler so each test gets a fresh one
    import backend.app.scheduler.core as score
    score._core = None
    sched = get_scheduler()
    await sched.start()
    yield sched
    await sched.shutdown()
    score._core = None
    await eng.dispose_engine()


@pytest.mark.asyncio
async def test_register_unknown_job_kind_rejected(temp_db_and_scheduler):
    sched = temp_db_and_scheduler
    with pytest.raises(ValueError, match="unknown job_kind"):
        await sched.register(
            name="bad", user_id="u", job_kind="no_such_kind",
            interval_seconds=60,
        )


@pytest.mark.asyncio
async def test_register_then_run_now_creates_draft(temp_db_and_scheduler):
    """Full HITL loop using protein_low_alert (deterministic w/ low data)."""
    sched = temp_db_and_scheduler

    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    # Seed user with no protein -> alert should fire
    async with session_scope() as s:
        await repo.upsert_user(s, "u-1")
        await repo.add_meal(
            s, "u-1", dishes=[{"name": "rice"}],
            total_kcal=200.0, total_protein_g=5.0,
        )

    await sched.register(
        name="u1-protein-watch",
        user_id="u-1",
        job_kind="protein_low_alert",
        cron_expr="0 8 * * *",
        payload={"days": 1, "target_protein_per_day": 60.0},
    )

    fired = await sched.run_now("u1-protein-watch")
    assert fired is True

    # Verify a draft notification exists
    from sqlalchemy import select
    from backend.app.db.models import Notification
    async with session_scope() as s:
        rows = list((await s.execute(
            select(Notification).where(Notification.user_id == "u-1")
        )).scalars().all())
    assert len(rows) == 1
    n = rows[0]
    assert n.status == "draft"
    assert n.kind == "protein_low_alert"
    assert "蛋白质" in n.body


@pytest.mark.asyncio
async def test_protein_alert_skipped_when_target_met(temp_db_and_scheduler):
    sched = temp_db_and_scheduler

    from backend.app.db import session_scope
    from backend.app.db import repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "u-2")
        await repo.add_meal(
            s, "u-2", dishes=[{"name": "egg"}],
            total_kcal=300, total_protein_g=80.0,
        )

    await sched.register(
        name="u2-protein", user_id="u-2", job_kind="protein_low_alert",
        interval_seconds=3600,
        payload={"days": 1, "target_protein_per_day": 60.0},
    )
    await sched.run_now("u2-protein")

    from sqlalchemy import select
    from backend.app.db.models import Notification
    async with session_scope() as s:
        rows = list((await s.execute(
            select(Notification).where(Notification.user_id == "u-2")
        )).scalars().all())
    assert rows == []  # no alert, no draft


@pytest.mark.asyncio
async def test_cancel_and_list(temp_db_and_scheduler):
    sched = temp_db_and_scheduler
    await sched.register(
        name="job-a", user_id="u", job_kind="daily_report",
        cron_expr="0 22 * * *", payload={"window_days": 7},
    )
    jobs = await sched.list_jobs("u")
    assert len(jobs) == 1 and jobs[0]["enabled"] is True
    assert jobs[0]["next_run_at"] is not None

    ok = await sched.cancel("job-a")
    assert ok
    jobs = await sched.list_jobs("u")
    assert len(jobs) == 1 and jobs[0]["enabled"] is False
