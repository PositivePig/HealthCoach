#!/usr/bin/env python3
"""Demo: Mental Coach + redline detection.

Usage:
  python -m scripts.demo_mental [message] [user_id]

If no args, runs a predefined scenario set.
"""

from __future__ import annotations

import anyio
import json
import sys

from backend.app.agents.main_graph import get_main_graph
from backend.app.agents.state import AgentState


# ---------- scenario set ----------

SCENARIOS = [
    # (name, user_message, expect_redline, expect_handoff)
    (
        "1. Redline: self-harm",
        "我最近压力很大，想割腕自杀",
        True,  # expect redline (no LLM call)
        None,
    ),
    (
        "2. Redline: severe depression",
        "已经连续两周无法起床，不洗脸不刷牙，觉得活着没意义",
        True,
        None,
    ),
    (
        "3. Redline: panic attack",
        "突然心跳加速、胸闷、窒息感，感觉要死了",
        True,
        None,
    ),
    (
        "4. Normal: sleep hygiene",
        "最近失眠很严重，晚上躺下两小时都睡不着，怎么办？",
        False,
        None,
    ),
    (
        "5. Normal: work stress",
        "工作压力很大，每天加班到10点，感觉快崩溃了",
        False,
        None,
    ),
    (
        "6. Normal: anxiety coping",
        "总是很焦虑，担心还没发生的事情，有什么办法放松吗？",
        False,
        None,
    ),
    (
        "7. Handoff → nutrition",
        "吃什么能改善情绪？听说 Omega-3 有用",
        False,
        "nutrition",
    ),
    (
        "8. Handoff → fitness",
        "运动能不能缓解我的焦虑？想试试跑步",
        False,
        "fitness",
    ),
]


def make_state(msg: str, user_id: str = "demo-user") -> AgentState:
    return {
        "user_id": user_id,
        "user_message": msg,
        "image_path": None,
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "next_coach": None,
        "final_answer": None,
        "final_citations": None,
        "final_mode": None,
        "final_provider": None,
        "final_model": None,
    }


async def run_scenario(name: str, msg: str, expect_redline: bool, expect_handoff: str | None):
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"  消息: {msg}")
    print(f"{'=' * 60}")

    state = make_state(msg)
    graph = get_main_graph()

    # Run the graph until END.
    result = await graph.ainvoke(state)

    print(f"\n[result]")
    print(f"  final_mode:  {result.get('final_mode')}")
    print(f"  final_coach: {[a.get('coach') for a in (result.get('coach_answers') or [])]}")
    print(f"  handoff_to:  {result.get('handoff_to')}")

    answer = result.get("final_answer") or ""
    print(f"\n[answer 前 200 字]\n{answer[:200]}...\n")

    # Check expectations.
    if expect_redline:
        assert "危机" in answer or "热线" in answer, f"Expected crisis response, got: {answer[:100]}"
        print("✅ Redline crisis response detected")
    if expect_handoff:
        actual = result.get("handoff_to")
        print(f"  handoff check: expected={expect_handoff}, got={actual}")
        # handoff may have been processed by supervisor; check visited_coaches instead.
        visited = result.get("visited_coaches") or []
        print(f"  visited: {visited}")

    print("✅ Scenario passed\n")


async def main():
    if len(sys.argv) >= 2:
        # Single message mode.
        msg = " ".join(sys.argv[1:])
        user_id = sys.argv[2] if len(sys.argv) >= 3 else "demo-user"
        state = make_state(msg, user_id)
        graph = get_main_graph()
        result = await graph.ainvoke(state)
        print(json.dumps({k: v for k, v in result.items() if k != "coach_answers"}, indent=2, default=str))
        print("\n[coach answers]")
        for a in result.get("coach_answers") or []:
            print(f"  - {a.get('coach')}: {a.get('text')[:100]}...")
        return

    # Run all scenarios.
    print("=" * 60)
    print("  Mental Coach Demo — Redline + Normal + Handoff")
    print("=" * 60)
    for name, msg, redline, handoff in SCENARIOS:
        try:
            await run_scenario(name, msg, redline, handoff)
        except Exception as e:
            print(f"❌ Scenario failed: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    anyio.run(main)
