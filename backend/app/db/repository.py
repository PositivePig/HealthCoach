"""High-level CRUD + aggregation helpers used by the MCP server and agents.

All operations are async, use parameterized SQL (via SQLAlchemy ORM/Core),
and accept a session. The MCP server passes session_scope() per call.

Security: ALL queries are parameterized; never f-string user input into SQL.
(Per project security rules, see SQL injection prevention.)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from .models import Activity, Meal, User, Vital

log = get_logger(__name__)


# ---------- users ----------


async def upsert_user(
    session: AsyncSession,
    user_id: str,
    *,
    name: str | None = None,
    goal: str | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
    target_kcal: float | None = None,
    allergies: list[str] | None = None,
    dislikes: list[str] | None = None,
    diseases: list[str] | None = None,
) -> User:
    """Create or update a user profile."""
    existing = await session.get(User, user_id)
    if existing is None:
        u = User(
            id=user_id,
            name=name or "",
            goal=goal or "maintenance",
            height_cm=height_cm or 170.0,
            weight_kg=weight_kg or 70.0,
            target_kcal=target_kcal or 2000.0,
            allergies=allergies or [],
            dislikes=dislikes or [],
            diseases=diseases or [],
        )
        session.add(u)
        await session.flush()
        return u
    if name is not None:
        existing.name = name
    if goal is not None:
        existing.goal = goal
    if height_cm is not None:
        existing.height_cm = height_cm
    if weight_kg is not None:
        existing.weight_kg = weight_kg
    if target_kcal is not None:
        existing.target_kcal = target_kcal
    if allergies is not None:
        existing.allergies = allergies
    if dislikes is not None:
        existing.dislikes = dislikes
    if diseases is not None:
        existing.diseases = diseases
    await session.flush()
    return existing


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


# ---------- meals ----------


async def add_meal(
    session: AsyncSession,
    user_id: str,
    *,
    dishes: list[dict[str, Any]],
    total_kcal: float = 0.0,
    total_protein_g: float = 0.0,
    total_carbs_g: float = 0.0,
    total_fat_g: float = 0.0,
    total_fiber_g: float = 0.0,
    confidence: float = 0.6,
    source: str = "photo",
    image_path: str | None = None,
    notes: str = "",
    ts: datetime | None = None,
) -> Meal:
    """Insert one meal event. Caller is responsible for ensuring user exists."""
    m = Meal(
        user_id=user_id,
        ts=ts or datetime.now(tz=timezone.utc),
        dishes=dishes,
        total_kcal=total_kcal,
        total_protein_g=total_protein_g,
        total_carbs_g=total_carbs_g,
        total_fat_g=total_fat_g,
        total_fiber_g=total_fiber_g,
        confidence=confidence,
        source=source,
        image_path=image_path,
        notes=notes,
    )
    session.add(m)
    await session.flush()
    return m


async def query_meals(
    session: AsyncSession,
    user_id: str,
    *,
    days: int = 7,
    limit: int = 100,
) -> list[Meal]:
    """Return meals from the last `days` days, newest first."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = (
        select(Meal)
        .where(Meal.user_id == user_id)
        .where(Meal.ts >= cutoff)
        .order_by(Meal.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def aggregate_nutrition(
    session: AsyncSession,
    user_id: str,
    *,
    days: int = 7,
) -> dict[str, Any]:
    """Sum + per-day average over the window."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = select(
        func.coalesce(func.sum(Meal.total_kcal), 0.0),
        func.coalesce(func.sum(Meal.total_protein_g), 0.0),
        func.coalesce(func.sum(Meal.total_carbs_g), 0.0),
        func.coalesce(func.sum(Meal.total_fat_g), 0.0),
        func.coalesce(func.sum(Meal.total_fiber_g), 0.0),
        func.count(Meal.id),
    ).where(Meal.user_id == user_id).where(Meal.ts >= cutoff)
    row = (await session.execute(stmt)).one()
    kcal, p, c, f, fib, n = row
    avg = (lambda x: round(x / max(days, 1), 1))
    return {
        "window_days": days,
        "total_kcal": round(kcal, 1),
        "total_protein_g": round(p, 1),
        "total_carbs_g": round(c, 1),
        "total_fat_g": round(f, 1),
        "total_fiber_g": round(fib, 1),
        "meal_count": int(n),
        "avg_kcal_per_day": avg(kcal),
        "avg_protein_per_day": avg(p),
        "avg_carbs_per_day": avg(c),
        "avg_fat_per_day": avg(f),
    }


# ---------- activities ----------


async def add_activity(
    session: AsyncSession,
    user_id: str,
    *,
    type: str,
    duration_min: float,
    intensity: str = "medium",
    hr_avg: float | None = None,
    calories_burned: float = 0.0,
    notes: str = "",
    source: str = "manual",
    ts: datetime | None = None,
) -> Activity:
    a = Activity(
        user_id=user_id,
        ts=ts or datetime.now(tz=timezone.utc),
        type=type,
        duration_min=duration_min,
        intensity=intensity,
        hr_avg=hr_avg,
        calories_burned=calories_burned,
        notes=notes,
        source=source,
    )
    session.add(a)
    await session.flush()
    return a


async def query_activities(
    session: AsyncSession,
    user_id: str,
    *,
    days: int = 14,
    limit: int = 100,
) -> list[Activity]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .where(Activity.ts >= cutoff)
        .order_by(Activity.ts.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------- vitals ----------


async def add_vital(
    session: AsyncSession,
    user_id: str,
    *,
    weight_kg: float | None = None,
    body_fat: float | None = None,
    hrv_ms: float | None = None,
    sleep_min: float | None = None,
    mood: str | None = None,
    notes: str = "",
    ts: datetime | None = None,
) -> Vital:
    v = Vital(
        user_id=user_id,
        ts=ts or datetime.now(tz=timezone.utc),
        weight_kg=weight_kg,
        body_fat=body_fat,
        hrv_ms=hrv_ms,
        sleep_min=sleep_min,
        mood=mood,
        notes=notes,
    )
    session.add(v)
    await session.flush()
    return v


async def query_vitals(
    session: AsyncSession,
    user_id: str,
    *,
    days: int = 30,
    limit: int = 200,
) -> list[Vital]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = (
        select(Vital)
        .where(Vital.user_id == user_id)
        .where(Vital.ts >= cutoff)
        .order_by(Vital.ts.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
