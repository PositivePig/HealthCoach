"""Repository-level tests against an in-memory-like temp sqlite."""

from __future__ import annotations

import pytest

from backend.app.db import repository as repo


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "repo.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.db import init_db
    await init_db()
    yield
    await eng.dispose_engine()


@pytest.mark.asyncio
async def test_upsert_user_create_and_update(temp_db):
    from backend.app.db import session_scope
    async with session_scope() as s:
        u = await repo.upsert_user(s, "u-x", name="Jason", goal="cut")
        assert u.id == "u-x"
        assert u.goal == "cut"

    async with session_scope() as s:
        u2 = await repo.upsert_user(s, "u-x", goal="bulk", weight_kg=80.5)
        assert u2.goal == "bulk"
        assert u2.weight_kg == 80.5
        assert u2.name == "Jason"  # unchanged


@pytest.mark.asyncio
async def test_meals_crud_and_aggregate(temp_db):
    from backend.app.db import session_scope
    async with session_scope() as s:
        await repo.upsert_user(s, "u-y")
        await repo.add_meal(
            s, "u-y", dishes=[{"name": "rice"}],
            total_kcal=300.0, total_protein_g=8.0,
            total_carbs_g=60.0, total_fat_g=2.0,
        )
        await repo.add_meal(
            s, "u-y", dishes=[{"name": "egg"}],
            total_kcal=80.0, total_protein_g=7.0,
            total_carbs_g=0.5, total_fat_g=5.5,
        )

    async with session_scope() as s:
        meals = await repo.query_meals(s, "u-y", days=7)
        assert len(meals) == 2
        agg = await repo.aggregate_nutrition(s, "u-y", days=7)
        assert agg["total_kcal"] == 380.0
        assert agg["total_protein_g"] == 15.0
        assert agg["meal_count"] == 2


@pytest.mark.asyncio
async def test_activities_and_vitals(temp_db):
    from backend.app.db import session_scope
    async with session_scope() as s:
        await repo.upsert_user(s, "u-z")
        await repo.add_activity(
            s, "u-z", type="run", duration_min=30, calories_burned=320
        )
        await repo.add_vital(s, "u-z", weight_kg=72.5, sleep_min=420)

    async with session_scope() as s:
        acts = await repo.query_activities(s, "u-z", days=14)
        assert len(acts) == 1 and acts[0].type == "run"
        vitals = await repo.query_vitals(s, "u-z", days=30)
        assert len(vitals) == 1 and vitals[0].weight_kg == 72.5
