"""Procedural Memory Store (KV-backed).

Stores per-user communication preferences and learned interaction patterns.

Uses:
  - PostgreSQL/SQLite `procedural_prefs` table (KV store)
  - Pydantic ProceduralProfile as the canonical schema

Design:
  - Each (user_id, key) is a row
  - value_json stores JSON-encoded values (str, number, bool, list, dict)
  - ProceduralProfile is serialized/deserialized from KV pairs
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..db.models import ProceduralPreference
from ..memory.types import (
    ProceduralProfile,
    CommunicationStyle,
    DetailLevel,
)

log = get_logger(__name__)

# Map Pydantic field names → default values
DEFAULT_PROFILE = ProceduralProfile(user_id="__template__")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_json_value(value: Any) -> str:
    """Convert a Python value to JSON string."""
    return json.dumps(value, ensure_ascii=False)


def _from_json_value(json_str: str) -> Any:
    """Parse a JSON string to Python value."""
    return json.loads(json_str)


def _profile_to_kv(
    profile: ProceduralProfile,
) -> list[tuple[str, str, str]]:
    """Convert a ProceduralProfile to a list of (key, value_json, updated_at).

    Returns list of (key, json_value, iso_timestamp).
    """
    now_str = datetime.now(tz=timezone.utc).isoformat()

    mapping: list[tuple[str, Any]] = [
        ("tone", profile.tone.value),
        ("detail_level", profile.detail_level.value),
        ("use_emoji", profile.use_emoji),
        ("use_units_metric", profile.use_units_metric),
        ("reminder_time", profile.reminder_time),
        ("reminder_freq", profile.reminder_freq),
        ("reminder_channels", profile.reminder_channels),
        ("coaching_style", profile.coaching_style),
        ("celebrate_wins", profile.celebrate_wins),
        ("gentle_nudges", profile.gentle_nudges),
        ("preferred_meal_times", profile.preferred_meal_times),
        ("preferred_workout_days", profile.preferred_workout_days),
        ("common_triggers", profile.common_triggers),
        ("version", profile.version),
    ]

    return [(k, _to_json_value(v), now_str) for k, v in mapping if v is not None]


def _kv_to_profile(
    user_id: str,
    kv_rows: list[ProceduralPreference],
) -> ProceduralProfile:
    """Build a ProceduralProfile from KV rows."""
    profile = ProceduralProfile(user_id=user_id)

    # Build lookup dict
    lookup: dict[str, Any] = {}
    updated_at: str | None = None

    for row in kv_rows:
        lookup[row.key] = _from_json_value(row.value_json)
        if row.updated_at:
            at_str = row.updated_at.isoformat()
            if updated_at is None or at_str > updated_at:
                updated_at = at_str

    # Apply lookups
    if "tone" in lookup:
        try:
            profile.tone = CommunicationStyle(lookup["tone"])
        except ValueError:
            pass
    if "detail_level" in lookup:
        try:
            profile.detail_level = DetailLevel(lookup["detail_level"])
        except ValueError:
            pass

    for field in [
        "use_emoji",
        "use_units_metric",
        "reminder_time",
        "reminder_freq",
        "coaching_style",
        "celebrate_wins",
        "gentle_nudges",
    ]:
        if field in lookup:
            setattr(profile, field, lookup[field])

    for field in [
        "reminder_channels",
        "preferred_meal_times",
        "preferred_workout_days",
        "common_triggers",
    ]:
        if field in lookup and isinstance(lookup[field], list):
            setattr(profile, field, lookup[field])

    if "version" in lookup and isinstance(lookup["version"], int):
        profile.version = lookup["version"]

    if updated_at:
        profile.updated_at = datetime.fromisoformat(updated_at)

    return profile


# ---------------------------------------------------------------------------
# ProceduralStore
# ---------------------------------------------------------------------------


class ProceduralStore:
    """KV-backed procedural memory store."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- read ---------------------------------------------------------------

    async def get(self, user_id: str) -> ProceduralProfile:
        """Get the full procedural profile for a user.

        Returns default profile if user has no stored preferences.
        """
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == user_id
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        if not rows:
            log.info("procedural_profile_not_found", user_id=user_id, action="return_default")
            return ProceduralProfile(user_id=user_id)

        profile = _kv_to_profile(user_id, rows)
        log.info(
            "procedural_profile_loaded",
            user_id=user_id,
            tone=profile.tone.value,
            detail=profile.detail_level.value,
        )
        return profile

    async def get_key(self, user_id: str, key: str) -> Any | None:
        """Get a single KV value."""
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == user_id,
            ProceduralPreference.key == key,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return _from_json_value(row.value_json)

    # -- write --------------------------------------------------------------

    async def set_key(
        self,
        user_id: str,
        key: str,
        value: Any,
    ) -> None:
        """Set a single KV value (upsert)."""
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == user_id,
            ProceduralPreference.key == key,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()

        now = datetime.now(tz=timezone.utc)

        if existing:
            existing.value_json = _to_json_value(value)
            existing.updated_at = now
        else:
            self.session.add(
                ProceduralPreference(
                    user_id=user_id,
                    key=key,
                    value_json=_to_json_value(value),
                    updated_at=now,
                )
            )

        await self.session.flush()
        log.info("procedural_key_set", user_id=user_id, key=key)

    async def update(
        self,
        user_id: str,
        patch: dict[str, Any],
    ) -> ProceduralProfile:
        """Partially update the profile with a patch dict.

        Only updates keys present in `patch`.
        Returns the updated full profile.
        """
        for key, value in patch.items():
            await self.set_key(user_id, key, value)

        # Bump version (ensure int, with fallback)
        current_raw = await self.get_key(user_id, "version")
        try:
            current = int(current_raw) if current_raw is not None else 0
        except (ValueError, TypeError):
            current = 0
        await self.set_key(user_id, "version", current + 1)

        profile = await self.get(user_id)
        log.info("procedural_profile_updated", user_id=user_id, patch_keys=list(patch.keys()))
        return profile

    async def set_profile(self, profile: ProceduralProfile) -> ProceduralProfile:
        """Overwrite the entire profile (full upsert)."""
        # Delete existing
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == profile.user_id
        )
        existing = (await self.session.execute(stmt)).scalars().all()
        for row in existing:
            await self.session.delete(row)

        # Insert all
        kv_pairs = _profile_to_kv(profile)
        now = datetime.now(tz=timezone.utc)

        for key, value_json, _ in kv_pairs:
            self.session.add(
                ProceduralPreference(
                    user_id=profile.user_id,
                    key=key,
                    value_json=value_json,
                    updated_at=now,
                )
            )

        await self.session.flush()
        log.info("procedural_profile_set_full", user_id=profile.user_id)

        return await self.get(profile.user_id)

    # -- delete -------------------------------------------------------------

    async def delete_key(self, user_id: str, key: str) -> bool:
        """Delete a single KV entry. Returns True if deleted."""
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == user_id,
            ProceduralPreference.key == key,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return False

        await self.session.delete(existing)
        await self.session.flush()
        log.info("procedural_key_deleted", user_id=user_id, key=key)
        return True

    async def delete_all(self, user_id: str) -> int:
        """Delete ALL procedural data for a user (GDPR-style).

        Returns the number of keys deleted.
        """
        stmt = select(ProceduralPreference).where(
            ProceduralPreference.user_id == user_id
        )
        existing = (await self.session.execute(stmt)).scalars().all()
        count = len(existing)

        for row in existing:
            await self.session.delete(row)

        await self.session.flush()
        log.info("procedural_profile_deleted_all", user_id=user_id, count=count)
        return count

    # -- implicit learning --------------------------------------------------

    async def learn_from_feedback(
        self,
        user_id: str,
        feedback: str,
    ) -> None:
        """Update procedural memory based on user feedback.

        Simple heuristic-based learning (W4). W5+ will use LLM.

        Examples:
          - "太啰嗦了" → detail_level = "brief"
          - "说简单点" → detail_level = "brief"
          - "多讲点" → detail_level = "detailed"
          - "别用表情" → use_emoji = False
          - "用英文" → (not implemented yet)
        """
        patch: dict[str, Any] = {}

        feedback_lower = feedback.lower()

        if any(w in feedback_lower for w in ["啰嗦", "太长", "简单点", "brief"]):
            patch["detail_level"] = "brief"
        elif any(w in feedback_lower for w in ["详细", "多讲", "detailed"]):
            patch["detail_level"] = "detailed"

        if any(w in feedback_lower for w in ["表情", "emoji", "别用表情"]):
            patch["use_emoji"] = False
        elif any(w in feedback_lower for w in ["表情", "emoji", "可以用表情"]):
            patch["use_emoji"] = True

        if any(w in feedback_lower for w in ["温柔", "暖", "warm"]):
            patch["tone"] = "warm"
        elif any(w in feedback_lower for w in ["直接", "direct"]):
            patch["tone"] = "direct"

        if patch:
            await self.update(user_id, patch)
            log.info(
                "procedural_learned_from_feedback",
                user_id=user_id,
                feedback=feedback[:50],
                patch=patch,
            )
