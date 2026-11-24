"""W3 D2 demo: bidirectional coach handoff.

Sends a single question that legitimately needs both coaches:
  "我刚力量训练完，应该怎么吃才能恢复？"

Heuristic routes fitness first (3 fitness keywords vs 1 nutrition keyword),
fitness coach answers and detects "怎么吃" → handoff to nutrition,
nutrition coach picks up and adds dietary specifics, finalize merges both.

Usage:
    uv run python scripts/demo_dual_handoff.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agents.main_graph import build_main_graph
from backend.app.db import init_db, repository as repo, session_scope


async def _seed(user_id: str) -> None:
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as s:
        await repo.upsert_user(
            s, user_id, name=user_id.title(), goal="muscle_gain",
            target_kcal=2700, weight_kg=72.0, height_cm=178.0,
        )
        # recent strength sessions
        for d in (1, 3, 5):
            await repo.add_activity(
                s, user_id, type="strength", duration_min=55, intensity="high",
                calories_burned=380, ts=now - timedelta(days=d),
            )
        # one tracked meal
        await repo.add_meal(
            s, user_id,
            dishes=[{"name": "鸡胸肉", "weight_g": 200, "kcal": 330,
                     "protein_g": 62, "carbs_g": 0, "fat_g": 7}],
            total_kcal=330, total_protein_g=62, total_fat_g=7,
            source="manual", ts=now - timedelta(hours=2),
        )


async def run(message: str, user_id: str) -> int:
    print(">>> [W3 D2 demo] dual-handoff: fitness ⇄ nutrition")
    print(f">>>   message = {message!r}")
    print(f">>>   user_id = {user_id}")

    await init_db()
    await _seed(user_id)

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": user_id,
        "user_message": message,
    })

    visited = out.get("visited_coaches") or []
    print()
    print("=== handoff trace ===")
    print(f"  visited order : {visited}")
    if visited == ["fitness", "nutrition"]:
        print("  ✓ fitness → nutrition handoff (forward)")
    elif visited == ["nutrition", "fitness"]:
        print("  ✓ nutrition → fitness handoff (reverse)")
    else:
        print("  ! unexpected visit order")

    print()
    print("=== coach answers ===")
    for ans in out.get("coach_answers") or []:
        print(f"\n[{ans['coach']}]  hits={ans.get('metadata', {}).get('rag_hits')}"
              f"  provider={ans.get('metadata', {}).get('provider')}")
        print(ans.get("text", ""))

    print()
    print("=== merged final answer ===")
    print(f"[{out.get('final_provider')}/{out.get('final_model')}]")
    print(out.get("final_answer", ""))

    print()
    print("=== final citations (deduped) ===")
    for c in out.get("final_citations") or []:
        print(f"  • {c['id']}  ({c.get('source')})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--message",
        default="我刚做完力量训练健身，应该怎么吃才能恢复，蛋白补多少？",
    )
    p.add_argument("--user-id", default="jason")
    args = p.parse_args()
    return asyncio.run(run(args.message, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
