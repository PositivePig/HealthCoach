"""W2 Day 2 demo: full pipeline with MCP food_vlm + health_db + LLM synth.

Usage:
    uv run python scripts/demo_nutrition_v2.py --image data/test_images/food.jpeg

What this exercises:
    - food_vlm MCP server (subprocess, stdio)        → recognize_food
    - health_db MCP server (subprocess, stdio)       → upsert_user_profile,
                                                       get_user_profile,
                                                       add_meal,
                                                       aggregate_nutrition
    - DeepSeek LLM via shared OpenAI-compatible router

Repeated runs accumulate into the SQLite DB (data/healthcoach.db); the
"history_summary" answer becomes more interesting over time.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agents.nutrition_v2_graph import build_nutrition_v2_graph


async def run(message: str, image: str, user_id: str) -> int:
    graph = build_nutrition_v2_graph()
    print(f">>> user_id : {user_id}")
    print(f">>> message : {message!r}")
    print(f">>> image   : {image!r}")
    print(">>> running graph (recognize -> db_io -> synthesize) ...\n")

    out = await graph.ainvoke(
        {
            "user_id": user_id,
            "user_message": message,
            "image_path": image,
        }
    )

    food = out.get("food_result") or {}
    if food.get("items"):
        items = ", ".join(i["name"] for i in food["items"])
        print(f"--- food_vlm ({food.get('mode')}) ---")
        print(f"  items   : {items}")
        print(f"  kcal    : {food.get('total_kcal')}")
        print(f"  protein : {food.get('total_protein_g')}g")
        print(f"  conf    : {food.get('overall_confidence')}")
        if food.get("notes"):
            print(f"  notes   : {food.get('notes')}")

    saved = out.get("saved_meal")
    if saved:
        print(f"\n--- meal saved ---  id={saved.get('id')}  ts={saved.get('ts')}")

    hist = out.get("history_summary")
    if hist:
        print(f"\n--- 7-day history (after this meal) ---")
        print(f"  meals       : {hist.get('meal_count')}")
        print(f"  total kcal  : {hist.get('total_kcal')}")
        print(f"  avg kcal/d  : {hist.get('avg_kcal_per_day')}")
        print(f"  avg protein : {hist.get('avg_protein_per_day')}g/d")

    print("\n--- coach answer ---")
    print(f"[{out.get('provider')}/{out.get('model')}]")
    print(out.get("final_answer", ""))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", default="jason")
    p.add_argument("--message", default="这餐怎么样？我想了解营养情况")
    p.add_argument("--image", default="data/test_images/food.jpeg")
    args = p.parse_args()
    return asyncio.run(run(args.message, args.image, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
