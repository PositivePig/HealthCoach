"""Type definitions for the three-layer memory system.

These types are shared across EpisodicStore, SemanticStore, ProceduralStore.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EventKind(str, Enum):
    """Types of episodic events."""

    MEAL = "meal"
    ACTIVITY = "activity"
    VITAL = "vital"
    CHAT = "chat"
    MOOD = "mood"
    SLEEP = "sleep"
    NOTE = "note"


class FactTag(str, Enum):
    """Semantic fact tags."""

    PROFILE = "profile"
    ALLERGY = "allergy"
    DISEASE = "disease"
    GOAL = "goal"
    PREFERENCE = "preference"
    DISLIKE = "dislike"
    INJURY = "injury"
    MEDICATION = "medication"
    LIFESTYLE = "lifestyle"
    OTHER = "other"


class CommunicationStyle(str, Enum):
    """Communication style preferences."""

    WARM = "warm"
    DIRECT = "direct"
    ENCOURAGING = "encouraging"
    NEUTRAL = "neutral"


class DetailLevel(str, Enum):
    """Response detail level."""

    BRIEF = "brief"
    MEDIUM = "medium"
    DETAILED = "detailed"


# ---------------------------------------------------------------------------
# Episodic Memory Types
# ---------------------------------------------------------------------------


class EpisodicEvent(BaseModel):
    """An episodic memory event.

    This is a unified representation of health events
    (meals, activities, vitals, chats, etc.).
    """

    id: str | None = None
    user_id: str
    kind: EventKind
    ts: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None  # LLM-generated summary (for old events)
    embedding_id: str | None = None  # Optional link to semantic memory

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Semantic Memory Types
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    """A semantic memory fact about the user."""

    id: str | None = None
    user_id: str
    fact: str  # The actual fact text
    tags: list[FactTag] = Field(default_factory=list)
    confidence: float = 1.0  # 0.0 - 1.0
    source: str = "user"  # "user" | "mem0" | "inference" | "profile"
    current: bool = True  # Is this the current truth?
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FactSearchResult(BaseModel):
    """A fact returned from semantic search."""

    fact: Fact
    score: float  # Similarity score


# ---------------------------------------------------------------------------
# Procedural Memory Types
# ---------------------------------------------------------------------------


class ProceduralProfile(BaseModel):
    """Procedural memory: how to interact with this user."""

    user_id: str

    # Communication style
    tone: CommunicationStyle = CommunicationStyle.WARM
    detail_level: DetailLevel = DetailLevel.MEDIUM
    use_emoji: bool = True
    use_units_metric: bool = True  # True: metric, False: imperial

    # Reminder preferences
    reminder_time: str | None = None  # "22:00" format
    reminder_freq: str = "daily"  # "daily" | "weekly" | "none"
    reminder_channels: list[str] = Field(default_factory=lambda: ["console"])

    # Coaching preferences
    coaching_style: str = "supportive"  # "supportive" | "strict" | "educational"
    celebrate_wins: bool = True
    gentle_nudges: bool = True

    # Learned patterns (implicit)
    preferred_meal_times: list[str] = Field(default_factory=list)  # ["08:00", "12:30", "18:00"]
    preferred_workout_days: list[str] = Field(default_factory=list)  # ["mon", "wed", "fri"]
    common_triggers: list[str] = Field(default_factory=list)  # ["stress", "late_night"]

    # Metadata
    version: int = 1
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Memory Query / Response Types
# ---------------------------------------------------------------------------


class MemoryContext(BaseModel):
    """Bundled memory context for use in agent prompts."""

    procedural: ProceduralProfile | None = None
    semantic_profile: list[Fact] = Field(default_factory=list)
    semantic_relevant: list[Fact] = Field(default_factory=list)
    episodic_recent: list[EpisodicEvent] = Field(default_factory=list)
    episodic_summary: str | None = None  # Compressed summary of older events

    def format_for_prompt(self) -> str:
        """Format the memory context for insertion into a system prompt."""
        parts: list[str] = []

        # Procedural
        if self.procedural:
            p = self.procedural
            parts.append(
                f"[沟通风格] 语气={p.tone.value}, 详细度={p.detail_level.value}, "
                f"emoji={'是' if p.use_emoji else '否'}"
            )
            if p.reminder_time:
                parts.append(f"[提醒] 时间={p.reminder_time}, 频率={p.reminder_freq}")

        # Semantic - Profile facts
        if self.semantic_profile:
            facts_str = "\n".join(f"  - {f.fact}" for f in self.semantic_profile)
            parts.append(f"[用户画像]\n{facts_str}")

        # Semantic - Relevant facts
        if self.semantic_relevant:
            facts_str = "\n".join(f"  - {f.fact}" for f in self.semantic_relevant)
            parts.append(f"[相关事实]\n{facts_str}")

        # Episodic - Recent events
        if self.episodic_recent:
            events_str = "\n".join(
                f"  - {e.ts.strftime('%m-%d %H:%M')} [{e.kind.value}] "
                f"{e.summary or str(e.payload)[:80]}"
                for e in self.episodic_recent[:10]  # Limit to 10 most recent
            )
            parts.append(f"[最近事件]\n{events_str}")

        # Episodic - Summary
        if self.episodic_summary:
            parts.append(f"[历史事件摘要]\n{self.episodic_summary}")

        return "\n\n".join(parts) if parts else "[无记忆上下文]"
