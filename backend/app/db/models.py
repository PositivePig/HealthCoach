"""SQLAlchemy ORM models.

Designed to be portable between SQLite (dev) and Postgres (prod):
  - Use sqlalchemy.JSON (works on both)
  - Use DateTime with timezone=True (sqlite stores as ISO text; pg uses TIMESTAMPTZ)
  - Composite (user_id, ts) indexes on time-series tables
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Shared declarative base."""


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------- users ----------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(256), default="")

    # User profile (semantic memory persistent layer)
    goal: Mapped[str] = mapped_column(String(64), default="maintenance")
    # 'maintenance' | 'cut' | 'bulk' | 'longevity' | etc.
    height_cm: Mapped[float] = mapped_column(Float, default=170.0)
    weight_kg: Mapped[float] = mapped_column(Float, default=70.0)
    target_kcal: Mapped[float] = mapped_column(Float, default=2000.0)

    # Free-form structured fields
    allergies: Mapped[list[str]] = mapped_column(JSON, default=list)
    dislikes: Mapped[list[str]] = mapped_column(JSON, default=list)
    diseases: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    meals: Mapped[list["Meal"]] = relationship(back_populates="user")
    activities: Mapped[list["Activity"]] = relationship(back_populates="user")
    vitals: Mapped[list["Vital"]] = relationship(back_populates="user")


# ---------- meals (episodic) ----------


class Meal(Base):
    """One eating event. dishes is the structured food_vlm output."""

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    # Raw structured result from food_vlm (RecognizeFoodResult.model_dump())
    dishes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Denormalized totals for fast queries / aggregations
    total_kcal: Mapped[float] = mapped_column(Float, default=0.0)
    total_protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_carbs_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_fiber_g: Mapped[float] = mapped_column(Float, default=0.0)

    confidence: Mapped[float] = mapped_column(Float, default=0.6)
    source: Mapped[str] = mapped_column(String(32), default="photo")
    # 'photo' | 'manual' | 'voice' | 'import'
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User"] = relationship(back_populates="meals")

    __table_args__ = (
        Index("ix_meals_user_ts", "user_id", "ts"),
    )


# ---------- activities ----------


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    type: Mapped[str] = mapped_column(String(64))  # run / walk / strength / yoga ...
    duration_min: Mapped[float] = mapped_column(Float, default=0.0)
    intensity: Mapped[str] = mapped_column(String(16), default="medium")
    hr_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories_burned: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="manual")

    user: Mapped["User"] = relationship(back_populates="activities")

    __table_args__ = (Index("ix_activities_user_ts", "user_id", "ts"),)


# ---------- vitals (weight / sleep / hrv) ----------


class Vital(Base):
    __tablename__ = "vitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User"] = relationship(back_populates="vitals")

    __table_args__ = (Index("ix_vitals_user_ts", "user_id", "ts"),)


# ---------- episodic memory (unified event log) ----------


class EpisodicEvent(Base):
    """Unified episodic event log for non-structured events.

    Structured events (meals, activities, vitals) remain in their
    respective tables; this table captures chat fragments, user notes,
    mood entries, and LLM-generated summaries.
    """

    __tablename__ = "episodic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # 'chat' | 'mood' | 'note' | 'summary' | 'feedback'

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True
    )

    # Event payload (flexible schema)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # LLM-generated summary (for old event compression, W5+)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link to a semantic fact (if this event triggered fact extraction)
    semantic_fact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_episodic_user_ts", "user_id", "ts"),
        Index("ix_episodic_user_kind", "user_id", "kind"),
    )


# ---------- procedural memory (KV preferences) ----------


class ProceduralPreference(Base):
    """KV store for per-user procedural memory (communication preferences).

    Each row is a (user_id, key, value_json) triple.
    The Pydantic model ProceduralProfile is the canonical schema;
    this table stores it as individual KV pairs for easy partial updates.
    """

    __tablename__ = "procedural_prefs"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # e.g. "tone", "detail_level", "reminder_time", ...

    value_json: Mapped[str] = mapped_column(Text)
    # JSON-encoded value (str, number, bool, list, dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_procedural_user", "user_id"),)


# ---------- scheduled jobs (persistent task definitions) ----------


class ScheduledJob(Base):
    """A user-owned scheduled job definition.

    The job is persisted here; on each app start, the scheduler core reads
    all enabled rows and registers them with APScheduler in-memory.
    """

    __tablename__ = "scheduled_jobs"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    job_kind: Mapped[str] = mapped_column(String(64))
    # built-in kinds: "daily_report" / "weekly_report" / "threshold_scan" / ...

    # Trigger spec: exactly one of cron_expr OR interval_seconds is set
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # standard 5-field cron: "min hour day mon dow"  e.g. "0 22 * * *"
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # arbitrary kwargs the job kind expects (e.g. {"window_days": 7})

    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "ok" | "error" | "pending"
    last_run_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


# ---------- notifications (HITL drafts) ----------


class Notification(Base):
    """A message proposed by an Agent (often via a scheduled job).

    Lifecycle:
        draft  -> approved -> sent
                \\-> rejected
    The 'notify' MCP server (W2 D4) reads `approved` rows and dispatches them.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64))
    # 'daily_report' | 'protein_alert' | 'reminder' | 'weekly_report' | ...

    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # draft | approved | rejected | sent | failed

    # delivery channel ("console" | "file" | "email"); set when approving
    channel: Mapped[str] = mapped_column(String(32), default="console")
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_notifications_user_status", "user_id", "status"),)
