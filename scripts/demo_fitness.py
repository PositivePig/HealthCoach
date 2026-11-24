"""W3 D2 demo: Fitness Coach via the main graph.

Routes a fitness question through the supervisor → fitness_coach → finalize
path, with optional bidirectional handoff to nutrition.

Usage:
    uv run python scripts/demo_fitness.py \
        --message "最近膝盖痛，跑步要不要停" --user-id jason

    uv run python scripts/demo_fitness.py \
        --message "我刚跑了 5 公里步频偏低，怎么提速并恢复" \
        --no-seed-history
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


async def _seed_history(user_id: str) -> None:
    """Insert a believable training + sleep history so the coach has data to cite."""
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as s:
        await repo.upsert_user(
            s, user_id, name=user_id.title(), goal="endurance",
            target_kcal=2400, weight_kg=72.0, height_cm=178.0,
        )
        # 14-day activity log: 3 runs + 2 strength
        runs = [(2, 30, "medium"), (5, 28, "medium"), (8, 45, "high")]
        for d, dur, intensity in runs:
            await repo.add_activity(
                s, user_id, type="run", duration_min=dur, intensity=intensity,
                hr_avg=152, calories_burned=dur * 10,
                ts=now - timedelta(days=d),
            )
        for d in (3, 6):
            await repo.add_activity(
                s, user_id, type="strength", duration_min=45, intensity="high",
                calories_burned=300, ts=now - timedelta(days=d),
            )
        # vitals: sleep + HRV
        for d in range(7):
            await repo.add_vital(
                s, user_id, sleep_min=420 + (d % 3) * 20,
                hrv_ms=58 - (d % 4),
                ts=now - timedelta(days=d),
            )


async def run(message: str, user_id: str, seed: bool) -> int:
    print(">>> [W3 D2 demo] supervisor + fitness coach + RAG")
    print(f">>>   message = {message!r}")
    print(f">>>   user_id = {user_id}   seed_history={seed}")

    await init_db()
    if seed:
        await _seed_history(user_id)

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": user_id,
        "user_message": message,
    })

    print()
    print("=== visited coaches ===")
    print("  ", out.get("visited_coaches"))

    print()
    print("=== coach answers ===")
    for ans in out.get("coach_answers") or []:
        print(f"\n[{ans['coach']}]  meta={ans.get('metadata')}")
        print(ans.get("text", ""))
        for c in ans.get("citations", []) or []:
            print(f"   • {c['id']}  (score={c.get('score')})  -- {c['source']}")
            print(f"       {c['quote'][:120]}{'...' if len(c['quote']) > 120 else ''}")

    print()
    print("=== final answer ===")
    print(f"[{out.get('final_provider')}/{out.get('final_model')}]")
    print(out.get("final_answer", ""))

    print()
    print("=== final citations ===")
    for c in out.get("final_citations") or []:
        print(f"  • {c['id']}  ({c.get('source')})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--message", default="最近膝盖前侧有点痛，跑步要不要停？")
    p.add_argument("--user-id", default="jason")
    p.add_argument("--no-seed-history", dest="seed", action="store_false")
    p.set_defaults(seed=True)
    args = p.parse_args()
    return asyncio.run(run(args.message, args.user_id, args.seed))


if __name__ == "__main__":
    raise SystemExit(main())
