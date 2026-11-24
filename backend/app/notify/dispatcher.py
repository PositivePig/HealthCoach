"""Dispatcher: pick approved notifications, send via their channel,
mark sent/failed accordingly. Idempotent + retry-aware.

Status machine recap:
  draft → approved → sent
                  → failed   (after max attempts)

A failed delivery increments delivery_attempts; the next dispatch tick
will retry up to MAX_ATTEMPTS, then mark status='failed'.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..core.logging import get_logger
from ..db import session_scope
from ..db.models import Notification
from .channels import ChannelError, get_channel

log = get_logger(__name__)

MAX_ATTEMPTS = 3


async def _deliver_one_internal(notification_id: int) -> dict[str, Any]:
    """Send a single approved Notification. Updates status in-place.

    Returns: {"id", "status", "attempts", "channel", "error"|None, "audit"|None}
    Raises only on bad input (id not found / wrong status).
    """
    async with session_scope() as session:
        n = await session.get(Notification, notification_id)
        if n is None:
            raise ValueError(f"notification {notification_id} not found")
        if n.status != "approved":
            raise ValueError(
                f"notification {notification_id} status={n.status} (must be 'approved')"
            )

        channel_name = n.channel or "console"
        title = n.title
        body = n.body
        user_id = n.user_id
        metadata = dict(n.metadata_json or {})
        attempts = n.delivery_attempts or 0

    # Send outside session to keep transaction short
    audit: dict[str, Any] | None = None
    error: str | None = None
    try:
        ch = get_channel(channel_name)
        if not ch.available:
            raise ChannelError(f"channel '{channel_name}' is not configured")
        audit = await ch.send(
            user_id=user_id, title=title, body=body, metadata=metadata
        )
        new_status = "sent"
    except (ChannelError, Exception) as e:  # noqa: BLE001
        error = str(e)
        attempts += 1
        new_status = "failed" if attempts >= MAX_ATTEMPTS else "approved"
        log.warning(
            "dispatch_failed",
            id=notification_id, attempt=attempts, status=new_status, error=error,
        )

    # Update DB
    async with session_scope() as session:
        n = await session.get(Notification, notification_id)
        if n is None:
            return {"id": notification_id, "status": "missing"}
        n.status = new_status
        if new_status == "sent":
            n.sent_at = datetime.now(tz=timezone.utc)
            n.delivery_error = None
        else:
            n.delivery_attempts = attempts
            n.delivery_error = error

    log.info(
        "dispatch_done",
        id=notification_id, status=new_status, channel=channel_name,
        attempts=attempts,
    )
    return {
        "id": notification_id,
        "status": new_status,
        "attempts": attempts,
        "channel": channel_name,
        "error": error,
        "audit": audit,
    }


async def dispatch_one(notification_id: int) -> dict[str, Any]:
    """Public single-message dispatch."""
    return await _deliver_one_internal(notification_id)


async def dispatch_pending(
    *, user_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Pick all approved notifications (optionally for one user) and send."""
    async with session_scope() as session:
        stmt = (
            select(Notification.id)
            .where(Notification.status == "approved")
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(Notification.user_id == user_id)
        ids = list((await session.execute(stmt)).scalars().all())

    results: list[dict[str, Any]] = []
    for nid in ids:
        try:
            results.append(await _deliver_one_internal(nid))
        except Exception as e:  # noqa: BLE001
            log.error("dispatch_one_failed", id=nid, error=str(e))
            results.append({"id": nid, "status": "error", "error": str(e)})
    return results
