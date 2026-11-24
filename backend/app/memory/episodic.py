"""Episodic Memory Store.

Stores and retrieves recent health events (meals, activities, vitals,
chat fragments, mood notes, etc.).

Uses:
  - Existing tables (meals, activities, vitals) for structured events
  - New `episodic_events` table for unstructured events (chat, mood, notes)

Recall strategy: time-windowed queries + optional kind filter.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..db.models import EpisodicEvent, Activity, Meal, Vital
from ..memory.types import EpisodicEvent as EpisodicEventModel, EventKind

log = get_logger(__name__)

# Default recall window
DEFAULT_DAYS = 7
MAX_EVENTS = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_pydantic(
    orm_event: EpisodicEvent,
) -> EpisodicEventModel:
    """Convert SQLAlchemy EpisodicEvent → Pydantic model."""
    return EpisodicEventModel(
        id=str(orm_event.id),
        user_id=orm_event.user_id,
        kind=EventKind(orm_event.kind),
        ts=orm_event.ts,
        payload=orm_event.payload or {},
        summary=orm_event.summary,
        embedding_id=orm_event.semantic_fact_id,  # reuse field for embedding link
    )


def _row_to_event(
    row: dict[str, Any],
    kind: EventKind,
    ts: datetime,
    summary: str | None = None,
) -> EpisodicEventModel:
    """Convert a generic DB row (dict) to an EpisodicEvent pydantic model."""
    return EpisodicEventModel(
        user_id=row.get("user_id", ""),
        kind=kind,
        ts=ts,
        payload=row,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# EpisodicStore
# ---------------------------------------------------------------------------


class EpisodicStore:
    """Unified episodic memory store.

    Combines structured events (meals/activities/vitals) with
    unstructured events (chat fragments, notes, mood entries).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- write ---------------------------------------------------------------

    async def add(
        self,
        user_id: str,
        kind: EventKind | str,
        payload: dict[str, Any],
        ts: datetime | None = None,
        summary: str | None = None,
    ) -> EpisodicEventModel:
        """Add an unstructured episodic event.

        For structured events (meals/activities/vitals), use the
        corresponding repository functions (add_meal, add_activity, add_vital).
        This method is for chat fragments, mood notes, user notes, etc.
        """
        k = kind.value if isinstance(kind, EventKind) else kind
        now = ts or datetime.now(tz=timezone.utc)

        evt = EpisodicEvent(
            user_id=user_id,
            kind=k,
            ts=now,
            payload=payload,
            summary=summary,
        )
        self.session.add(evt)
        await self.session.flush()
        await self.session.refresh(evt)

        log.info("episodic_event_added", user_id=user_id, kind=k, id=evt.id)
        return _to_pydantic(evt)

    # -- read (unstructured) ------------------------------------------------

    async def query_unstructured(
        self,
        user_id: str,
        *,
        kind: EventKind | str | None = None,
        days: int = DEFAULT_DAYS,
        limit: int = MAX_EVENTS,
    ) -> list[EpisodicEventModel]:
        """Query unstructured events from `episodic_events` table."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(EpisodicEvent)
            .where(
                EpisodicEvent.user_id == user_id,
                EpisodicEvent.ts >= cutoff,
            )
            .order_by(EpisodicEvent.ts.desc())
            .limit(limit)
        )
        if kind is not None:
            k = kind.value if isinstance(kind, EventKind) else kind
            stmt = stmt.where(EpisodicEvent.kind == k)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_pydantic(r) for r in rows]

    # -- read (structured) --------------------------------------------------

    async def query_meals(
        self,
        user_id: str,
        *,
        days: int = DEFAULT_DAYS,
        limit: int = MAX_EVENTS,
    ) -> list[dict[str, Any]]:
        """Return recent meals as event-like dicts."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(Meal)
            .where(Meal.user_id == user_id, Meal.ts >= cutoff)
            .order_by(Meal.ts.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "ts": r.ts,
                "total_kcal": r.total_kcal,
                "total_protein_g": r.total_protein_g,
                "total_carbs_g": r.total_carbs_g,
                "total_fat_g": r.total_fat_g,
                "confidence": r.confidence,
                "source": r.source,
                "notes": r.notes,
                "dishes_count": len(r.dishes) if r.dishes else 0,
            }
            for r in rows
        ]

    async def query_activities(
        self,
        user_id: str,
        *,
        days: int = 14,
        limit: int = MAX_EVENTS,
    ) -> list[dict[str, Any]]:
        """Return recent activities as event-like dicts."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(Activity)
            .where(Activity.user_id == user_id, Activity.ts >= cutoff)
            .order_by(Activity.ts.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "ts": r.ts,
                "type": r.type,
                "duration_min": r.duration_min,
                "intensity": r.intensity,
                "calories_burned": r.calories_burned,
                "notes": r.notes,
            }
            for r in rows
        ]

    async def query_vitals(
        self,
        user_id: str,
        *,
        days: int = 30,
        limit: int = MAX_EVENTS,
    ) -> list[dict[str, Any]]:
        """Return recent vitals as event-like dicts."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(Vital)
            .where(Vital.user_id == user_id, Vital.ts >= cutoff)
            .order_by(Vital.ts.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "ts": r.ts,
                "weight_kg": r.weight_kg,
                "body_fat": r.body_fat,
                "hrv_ms": r.hrv_ms,
                "sleep_min": r.sleep_min,
                "mood": r.mood,
                "notes": r.notes,
            }
            for r in rows
        ]

    # -- unified query -------------------------------------------------------

    async def query_all(
        self,
        user_id: str,
        *,
        days: int = DEFAULT_DAYS,
        limit_per_kind: int = 50,
        include_unstructured: bool = True,
    ) -> dict[str, list[Any]]:
        """Return all episodic data as a unified dict.

        Returns:
            {
                "meals": [...],
                "activities": [...],
                "vitals": [...],
                "unstructured": [...],  # chat, mood, notes
            }
        """
        meals = await self.query_meals(user_id, days=days, limit=limit_per_kind)
        activities = await self.query_activities(
            user_id, days=max(days, 14), limit=limit_per_kind
        )
        vitals = await self.query_vitals(
            user_id, days=max(days, 30), limit=limit_per_kind
        )

        result: dict[str, list[Any]] = {
            "meals": meals,
            "activities": activities,
            "vitals": vitals,
        }

        if include_unstructured:
            unstructured = await self.query_unstructured(
                user_id, days=days, limit=limit_per_kind
            )
            result["unstructured"] = [
                {
                    "id": e.id,
                    "kind": e.kind.value,
                    "ts": e.ts,
                    "payload": e.payload,
                    "summary": e.summary,
                }
                for e in unstructured
            ]

        return result

    # -- aggregation helpers -------------------------------------------------

    async def aggregate_meals(
        self,
        user_id: str,
        *,
        days: int = 7,
    ) -> dict[str, Any]:
        """Aggregate meal nutrition over a time window.

        Returns totals + per-day averages.
        """
        from ..db.repository import aggregate_nutrition

        return await aggregate_nutrition(self.session, user_id, days=days)

    async def aggregate_activities(
        self,
        user_id: str,
        *,
        days: int = 14,
    ) -> dict[str, Any]:
        """Aggregate activity durations by type."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(Activity)
            .where(Activity.user_id == user_id, Activity.ts >= cutoff)
            .order_by(Activity.ts.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        type_totals: dict[str, float] = {}
        type_count: dict[str, int] = {}
        total_min = 0.0

        for r in rows:
            t = r.type
            type_totals[t] = type_totals.get(t, 0.0) + r.duration_min
            type_count[t] = type_count.get(t, 0) + 1
            total_min += r.duration_min

        return {
            "window_days": days,
            "total_minutes": round(total_min, 1),
            "activity_count": len(rows),
            "by_type": {
                t: {"minutes": round(m, 1), "count": type_count[t]}
                for t, m in type_totals.items()
            },
            "avg_minutes_per_day": round(total_min / max(days, 1), 1),
        }

    # -- compression (W5+) ---------------------------------------------------

    async def compress_old_events(
        self,
        user_id: str,
        *,
        older_than_days: int = 30,
        keep_summary: bool = True,
    ) -> int:
        """Compress old unstructured events into a summary.

        W5+ feature: uses LLM to summarize old events,
        then marks them as compressed (or deletes them).

        Returns the number of events compressed.
        """
        # Placeholder for W5 implementation
        log.info(
            "compress_old_events_placeholder",
            user_id=user_id,
            older_than_days=older_than_days,
        )
        return 0
