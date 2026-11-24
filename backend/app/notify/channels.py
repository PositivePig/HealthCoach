"""Notification delivery channels.

A channel is a pluggable backend that takes a Notification and "sends" it.
At minimum we ship:
  - ConsoleChannel: prints to stderr (dev default)
  - FileChannel:    appends to a JSONL file (test friendly + audit trail)
  - EmailChannel:   SMTP (lazy: only used if SMTP env vars are set)

To add a new channel (e.g. WeChat, Telegram), implement BaseChannel and
register it in the registry below.
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from ..core.logging import get_logger

log = get_logger(__name__)


class ChannelError(Exception):
    """Raised when a channel fails to deliver."""


class BaseChannel(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether the channel is configured (has needed env, etc.)."""

    @abstractmethod
    async def send(
        self,
        *,
        user_id: str,
        title: str,
        body: str,
        metadata: dict,
    ) -> dict:
        """Deliver a single notification. Return a small dict for audit."""


# ---------- console ----------


class ConsoleChannel(BaseChannel):
    name = "console"

    @property
    def available(self) -> bool:
        return True

    async def send(self, *, user_id, title, body, metadata) -> dict:
        # Use stderr so it doesn't pollute MCP stdio stdout.
        print(
            f"\n[notify→console] user_id={user_id}\n"
            f"  title : {title}\n"
            f"  body  : {body}\n",
            file=sys.stderr,
            flush=True,
        )
        return {"channel": self.name, "delivered_at": datetime.now(tz=timezone.utc).isoformat()}


# ---------- file ----------


class FileChannel(BaseChannel):
    """Append-only JSONL delivery to a local file. Useful for tests + audit."""

    name = "file"

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        # default: ./data/notifications.jsonl
        self._path = Path(path or os.getenv("NOTIFY_FILE_PATH", "./data/notifications.jsonl"))

    @property
    def available(self) -> bool:
        return True

    async def send(self, *, user_id, title, body, metadata) -> dict:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "user_id": user_id,
            "title": title,
            "body": body,
            "metadata": metadata,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {
            "channel": self.name,
            "path": str(self._path),
            "delivered_at": record["ts"],
        }


# ---------- email ----------


class EmailChannel(BaseChannel):
    """Vanilla SMTP. Configured via env:
        NOTIFY_SMTP_HOST, NOTIFY_SMTP_PORT (default 465 for SSL, 587 for STARTTLS),
        NOTIFY_SMTP_USER, NOTIFY_SMTP_PASSWORD,
        NOTIFY_SMTP_FROM (default = user),
        NOTIFY_SMTP_TLS = "ssl" | "starttls" (default ssl),
        NOTIFY_EMAIL_TO_BY_USER = JSON dict mapping user_id → recipient email.
    """

    name = "email"

    def __init__(self) -> None:
        self.host = os.getenv("NOTIFY_SMTP_HOST", "")
        self.port = int(os.getenv("NOTIFY_SMTP_PORT", "465"))
        self.user = os.getenv("NOTIFY_SMTP_USER", "")
        self.password = os.getenv("NOTIFY_SMTP_PASSWORD", "")
        self.sender = os.getenv("NOTIFY_SMTP_FROM", self.user)
        self.tls = os.getenv("NOTIFY_SMTP_TLS", "ssl").lower()
        try:
            self._user_to = json.loads(os.getenv("NOTIFY_EMAIL_TO_BY_USER", "{}"))
        except json.JSONDecodeError:
            self._user_to = {}

    @property
    def available(self) -> bool:
        return bool(self.host and self.user and self.password)

    def _resolve_recipient(self, user_id: str) -> str:
        addr = self._user_to.get(user_id)
        if not addr:
            raise ChannelError(
                f"no email recipient for user_id={user_id} "
                f"(set NOTIFY_EMAIL_TO_BY_USER='{{\"{user_id}\":\"a@b.com\"}}')"
            )
        return addr

    async def send(self, *, user_id, title, body, metadata) -> dict:
        if not self.available:
            raise ChannelError("email channel not configured (missing SMTP env)")

        to_addr = self._resolve_recipient(user_id)

        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to_addr
        msg["Subject"] = title
        msg.set_content(body)

        # SMTP is sync; we do the send in a single shot. For a busy system this
        # should be wrapped via asyncio.to_thread; for our scale it's fine.
        try:
            if self.tls == "starttls":
                with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                    smtp.starttls()
                    smtp.login(self.user, self.password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as smtp:
                    smtp.login(self.user, self.password)
                    smtp.send_message(msg)
        except Exception as e:  # noqa: BLE001
            raise ChannelError(f"smtp send failed: {e}") from e

        return {
            "channel": self.name,
            "to": to_addr,
            "delivered_at": datetime.now(tz=timezone.utc).isoformat(),
        }


# ---------- registry ----------


_REGISTRY: dict[str, BaseChannel] | None = None


def get_channel(name: str) -> BaseChannel:
    """Return a registered channel instance, or raise."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {
            "console": ConsoleChannel(),
            "file": FileChannel(),
            "email": EmailChannel(),
        }
    if name not in _REGISTRY:
        raise ChannelError(f"unknown channel '{name}' (known: {sorted(_REGISTRY)})")
    return _REGISTRY[name]


def list_channels() -> list[dict]:
    """Status snapshot for /list_channels tool."""
    global _REGISTRY
    if _REGISTRY is None:
        get_channel("console")  # init
    out: list[dict] = []
    for name, ch in (_REGISTRY or {}).items():
        out.append({"name": name, "available": ch.available})
    return out


def reset_registry() -> None:
    """Test helper: rebuild channels (so env changes take effect)."""
    global _REGISTRY
    _REGISTRY = None
