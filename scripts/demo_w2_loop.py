"""W2 closing demo: full proactive loop.

Flow:
  1. recognize a meal photo via food_vlm   (W2 D1, MCP subprocess)
  2. save it via health_db                  (W2 D2, MCP subprocess)
  3. register a daily_report scheduled job  (W2 D3, scheduler)
  4. fire it once via run_now → DeepSeek drafts a Notification
  5. HITL approve (auto here for demo) with channel=file
  6. notify dispatch_pending → writes to ./data/notifications.jsonl
  7. show before/after status counts

Usage:
    bash scripts/dev.sh demo-w2-loop  data/test_images/food.jpeg jason
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select


async def run(image: str, user_id: str) -> int:
    print(">>> [W2 closing demo] full proactive loop")
    print(f">>>   image={image}")
    print(f">>>   user_id={user_id}")

    # ---- 1) recognize + save (reuse W2D2 graph) ----
    from backend.app.agents.nutrition_v2_graph import build_nutrition_v2_graph
    print("\n[1/5] running nutrition_v2_graph (food_vlm + health_db + LLM synth) ...")
    g = build_nutrition_v2_graph()
    out = await g.ainvoke({
        "user_id": user_id,
        "user_message": "今天午餐",
        "image_path": image,
    })
    food = out.get("food_result") or {}
    print(f"      → {len(food.get('items', []))} 食材，{food.get('total_kcal')} kcal")

    # ---- 2) scheduler: register + run_now ----
    from backend.app.db import init_db, session_scope
    from backend.app.db import repository as repo
    await init_db()
    async with session_scope() as s:
        await repo.upsert_user(s, user_id)

    from backend.app.scheduler import get_scheduler
    sched = get_scheduler()
    await sched.start()

    job_name = f"{user_id}-daily-report"
    print(f"\n[2/5] registering job '{job_name}' ...")
    await sched.register(
        name=job_name,
        user_id=user_id,
        job_kind="daily_report",
        cron_expr="0 22 * * *",
        payload={"window_days": 7},
    )

    print(f"[3/5] firing '{job_name}' now (drafts a notification) ...")
    await sched.run_now(job_name)

    # ---- 4) auto-approve latest draft with channel=file ----
    from backend.app.db.models import Notification
    print("\n[4/5] HITL approve (channel=file) ...")
    async with session_scope() as s:
        rows = list((await s.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.status == "draft")
            .order_by(Notification.created_at.desc())
        )).scalars().all())
        if not rows:
            print("      ⚠️  no draft found, demo aborted")
            await sched.shutdown()
            return 1
        target = rows[0]
        print(f"      approving id={target.id} title={target.title}")
        target.status = "approved"
        target.channel = "file"
        target.decided_at = datetime.now(tz=timezone.utc)

    # ---- 5) dispatch_pending ----
    from backend.app.notify import dispatch_pending
    print("\n[5/5] notify.dispatch_pending() ...")
    results = await dispatch_pending(user_id=user_id)
    for r in results:
        print(f"      id={r['id']}  status={r['status']}  channel={r.get('channel')}")

    # show status counts
    from sqlalchemy import func
    async with session_scope() as s:
        stmt = select(Notification.status, func.count(Notification.id)).where(
            Notification.user_id == user_id
        ).group_by(Notification.status)
        rows = (await s.execute(stmt)).all()
    print("\n--- status counts ---")
    for st, n in rows:
        print(f"   {st:10s}  {n}")

    # show last delivered file record
    out_path = Path("./data/notifications.jsonl")
    if out_path.exists():
        tail = out_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(tail)
        print(f"\n--- delivered (file channel: {out_path}) ---")
        print(f"   ts     : {rec['ts']}")
        print(f"   user   : {rec['user_id']}")
        print(f"   title  : {rec['title']}")
        print(f"   body   : {rec['body'][:200]}{'...' if len(rec['body'])>200 else ''}")

    await sched.shutdown()
    print("\n>>> done.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--image", default="data/test_images/food.jpeg")
    p.add_argument("--user-id", default="jason")
    args = p.parse_args()
    return asyncio.run(run(args.image, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
