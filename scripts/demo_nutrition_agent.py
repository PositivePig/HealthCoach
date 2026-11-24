"""W2 demo: end-to-end nutrition agent.

Day 2 update: identifies food → persists to SQLite → fetches 7-day aggregate →
LLM synthesizes a coach answer that references trends.

Usage:
    uv run python scripts/demo_nutrition_agent.py --image data/test_images/food.jpeg
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agents.nutrition_demo_graph import build_nutrition_demo_graph


async def run(message: str, image: str | None, user_id: str) -> int:
    graph = build_nutrition_demo_graph()
    print(f">>> user_id: {user_id}")
    print(f">>> message: {message!r}")
    print(f">>> image:   {image!r}")
    print(">>> running graph: call_food_vlm → persist_meal → fetch_history → synthesize")
    out = await graph.ainvoke(
        {"user_id": user_id, "user_message": message, "image_path": image}
    )

    food = out.get("food_result")
    if food and "items" in food:
        items = ", ".join(i["name"] for i in food["items"])
        print(f"\n--- food_vlm output ({food.get('mode')}) ---")
        print(f"items:   {items}")
        print(f"kcal:    {food.get('total_kcal')}")
        print(f"protein: {food.get('total_protein_g')}g")

    if out.get("meal_id") is not None:
        print(f"\n--- persisted meal_id = {out['meal_id']} ---")

    history = out.get("history_summary")
    if history:
        agg = history["weekly_aggregate"]
        print(f"--- 7-day aggregate ---")
        print(f"meal_count: {agg['meal_count']}")
        print(f"avg_kcal/day: {agg['avg_kcal_per_day']}")
        print(f"avg_protein/day: {agg['avg_protein_per_day']}g")
        print(f"profile: {history['profile']}")

    print("\n--- coach answer ---")
    print(f"[{out.get('provider')}/{out.get('model')}]")
    print(out.get("final_answer", ""))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--message", default="这餐吃得怎么样？")
    p.add_argument("--image", default="data/test_images/food.jpeg")
    p.add_argument("--user-id", default="jason")
    args = p.parse_args()
    return asyncio.run(run(args.message, args.image, args.user_id))


if __name__ == "__main__":
    raise SystemExit(main())
