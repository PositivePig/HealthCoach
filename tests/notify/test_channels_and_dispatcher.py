"""Tests for notify channels + dispatcher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.notify.channels import (
    ChannelError,
    ConsoleChannel,
    FileChannel,
    EmailChannel,
    get_channel,
    list_channels,
    reset_registry,
)


# ---------- channels ----------


@pytest.mark.asyncio
async def test_console_channel_send_returns_audit():
    ch = ConsoleChannel()
    out = await ch.send(
        user_id="u1", title="hi", body="body text", metadata={}
    )
    assert out["channel"] == "console"
    assert "delivered_at" in out


@pytest.mark.asyncio
async def test_file_channel_appends_jsonl(tmp_path: Path):
    p = tmp_path / "n.jsonl"
    ch = FileChannel(path=p)
    await ch.send(user_id="u", title="t1", body="b1", metadata={"k": 1})
    await ch.send(user_id="u", title="t2", body="b2", metadata={"k": 2})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    assert rec1["title"] == "t1" and rec1["metadata"]["k"] == 1


def test_email_channel_unconfigured_is_unavailable(monkeypatch):
    for k in (
        "NOTIFY_SMTP_HOST", "NOTIFY_SMTP_USER", "NOTIFY_SMTP_PASSWORD",
        "NOTIFY_SMTP_FROM", "NOTIFY_EMAIL_TO_BY_USER",
    ):
        monkeypatch.delenv(k, raising=False)
    ch = EmailChannel()
    assert ch.available is False


@pytest.mark.asyncio
async def test_email_channel_unconfigured_send_raises():
    ch = EmailChannel()
    with pytest.raises(ChannelError):
        await ch.send(user_id="u", title="t", body="b", metadata={})


def test_get_channel_unknown_raises():
    with pytest.raises(ChannelError):
        get_channel("does-not-exist")


def test_list_channels_lists_three():
    reset_registry()
    items = list_channels()
    names = {c["name"] for c in items}
    assert names == {"console", "file", "email"}


# ---------- dispatcher ----------


@pytest.fixture
async def temp_db_with_user(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "n.db"))
    monkeypatch.setenv("NOTIFY_FILE_PATH", str(tmp_path / "out.jsonl"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    reset_registry()  # rebuild channels with new env

    from backend.app.db import init_db
    await init_db()

    from backend.app.db import session_scope, repository as repo
    async with session_scope() as s:
        await repo.upsert_user(s, "u1")
    yield tmp_path
    await eng.dispose_engine()


async def _add_notification(*, user_id, status, channel="file"):
    from backend.app.db import session_scope
    from backend.app.db.models import Notification
    async with session_scope() as s:
        n = Notification(
            user_id=user_id, kind="test", title="hello", body="world",
            metadata_json={"x": 1}, status=status, channel=channel,
        )
        s.add(n)
        await s.flush()
        return n.id


@pytest.mark.asyncio
async def test_dispatch_one_marks_sent_and_writes_file(temp_db_with_user):
    nid = await _add_notification(user_id="u1", status="approved", channel="file")

    from backend.app.notify import dispatch_one
    result = await dispatch_one(nid)
    assert result["status"] == "sent"
    assert result["channel"] == "file"
    assert result["audit"] is not None

    # File written
    out = (temp_db_with_user / "out.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(out)
    assert rec["title"] == "hello" and rec["user_id"] == "u1"

    # Status flipped
    from backend.app.db import session_scope
    from backend.app.db.models import Notification
    async with session_scope() as s:
        n = await s.get(Notification, nid)
        assert n.status == "sent"
        assert n.sent_at is not None


@pytest.mark.asyncio
async def test_dispatch_one_wrong_status_raises(temp_db_with_user):
    nid = await _add_notification(user_id="u1", status="draft")
    from backend.app.notify import dispatch_one
    with pytest.raises(ValueError, match="must be 'approved'"):
        await dispatch_one(nid)


@pytest.mark.asyncio
async def test_dispatch_one_unknown_channel_marks_retry_then_failed(
    temp_db_with_user, monkeypatch
):
    """A misconfigured email channel should retry up to MAX_ATTEMPTS=3 then fail."""
    nid = await _add_notification(user_id="u1", status="approved", channel="email")

    from backend.app.notify import dispatch_one, MAX_ATTEMPTS

    # Attempts 1..2: stays 'approved' (retryable)
    for i in range(1, MAX_ATTEMPTS):
        r = await dispatch_one(nid)
        assert r["status"] == "approved"
        assert r["attempts"] == i

    # Attempt 3: marks 'failed'
    r = await dispatch_one(nid)
    assert r["status"] == "failed"
    assert r["attempts"] == MAX_ATTEMPTS

    # Subsequent dispatch_one fails (status is no longer approved)
    with pytest.raises(ValueError):
        await dispatch_one(nid)


@pytest.mark.asyncio
async def test_dispatch_pending_filters_by_user(temp_db_with_user):
    from backend.app.db import session_scope, repository as repo
    async with session_scope() as s:
        await repo.upsert_user(s, "u2")

    nid_a = await _add_notification(user_id="u1", status="approved", channel="file")
    nid_b = await _add_notification(user_id="u2", status="approved", channel="file")
    nid_draft = await _add_notification(user_id="u1", status="draft", channel="file")

    from backend.app.notify import dispatch_pending
    res = await dispatch_pending(user_id="u1")
    sent_ids = [r["id"] for r in res if r.get("status") == "sent"]
    assert sent_ids == [nid_a]
    assert nid_b not in sent_ids
    assert nid_draft not in sent_ids
