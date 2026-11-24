"""W3 D1 demo: multi-coach Supervisor + Nutrition Coach + RAG.

Compared to W2 D2's nutrition_v2_graph (linear: vlm → db → llm), this demo
runs the full LangGraph supervisor that:
  1. routes via heuristic (image_path → nutrition)
  2. nutrition coach pulls user profile + recent stats + RAG cites
  3. (placeholder) handoff back to supervisor; in W3 D2 fitness coach picks up
  4. finalize merges + emits citations

Usage:
    uv run python scripts/demo_supervisor.py --image data/test_images/food.jpeg \
                                              --message "我目标减脂，这餐够吗？" \
                                              --user-id jason
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agents.main_graph import build_main_graph
from backend.app.db import init_db, repository as repo, session_scope


async def run(image: str, message: str, user_id: str) -> int:
    print(f">>> [W3 D1 demo] supervisor + nutrition coach + RAG")
    print(f">>>   image    = {image}")
    print(f">>>   message  = {message!r}")
    print(f">>>   user_id  = {user_id}")

    # Ensure user has a profile so the coach can reason about goals
    await init_db()
    async with session_scope() as s:
        await repo.upsert_user(
            s, user_id, name=user_id.title(), goal="cut",
            target_kcal=1700, weight_kg=70.0,
            allergies=[],
        )

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": user_id,
        "user_message": message,
        "image_path": image,
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
            print(f"       {c['quote'][:120]}{'...' if len(c['quote'])>120 else ''}")

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
    p.add_argument("--image", default="data/test_images/food.jpeg")
    p.add_argument("--message", default="我目标减脂，这餐够吗？")
    p.add_argument("--user-id", default="jason")
    args = p.parse_args()
    return asyncio.run(run(args.image, args.message, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
