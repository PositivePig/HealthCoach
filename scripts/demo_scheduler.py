"""W2 D3 demo: end-to-end scheduler + HITL.

Steps:
  1. ensure user has at least 1 meal (re-run W2D2 demo if needed)
  2. register a daily_report job for the user
  3. run_now → daily_report job aggregates DB + asks DeepSeek + drafts a Notification
  4. list draft notifications
  5. approve one → status flip
  6. show final state

Usage:
    uv run python scripts/demo_scheduler.py --user-id jason
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.db import init_db, session_scope
from backend.app.db import repository as repo
from backend.app.scheduler import get_scheduler
from sqlalchemy import select
from backend.app.db.models import Notification


async def run(user_id: str) -> int:
    print(f">>> ensuring DB ready, user_id={user_id}")
    await init_db()

    # Make sure the user exists (idempotent)
    async with session_scope() as s:
        await repo.upsert_user(s, user_id)

    sched = get_scheduler()
    await sched.start()

    job_name = f"{user_id}-daily-report"
    print(f">>> registering job '{job_name}' (cron 22:00 every day)")
    await sched.register(
        name=job_name,
        user_id=user_id,
        job_kind="daily_report",
        cron_expr="0 22 * * *",
        payload={"window_days": 7},
    )

    print(">>> firing it now (run_now)")
    await sched.run_now(job_name)

    print()
    print("--- jobs ---")
    for j in await sched.list_jobs(user_id):
        print(
            f"  {j['name']:30s}  status={j['last_run_status']}  "
            f"next={j['next_run_at']}"
        )

    print()
    print("--- inbox: drafts ---")
    async with session_scope() as s:
        rows = list((await s.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.status == "draft")
            .order_by(Notification.created_at.desc())
        )).scalars().all())
        for n in rows:
            print(f"\n[id={n.id}] {n.title}")
            print(n.body)

    if rows:
        target = rows[0]
        print(f"\n--- approving draft id={target.id} (HITL) ---")
        async with session_scope() as s:
            row = await s.get(Notification, target.id)
            row.status = "approved"
            from datetime import datetime, timezone
            row.decided_at = datetime.now(tz=timezone.utc)
        print("    ok → status=approved (notify MCP will send in W2 D4)")

    await sched.shutdown()
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", default="jason")
    args = p.parse_args()
    return asyncio.run(run(args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
