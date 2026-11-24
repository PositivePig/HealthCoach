"""LangGraph + MCP client integration demo (W2 milestone).

Day 2 update:
  - Persist the recognized meal into health_db (via repository, in-process)
  - Pre-fetch this user's 7-day nutrition aggregate to inform the synthesizer

Pipeline:
  call_food_vlm  →  persist_meal  →  fetch_history  →  synthesize
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..core.langfuse_client import get_langfuse
from ..core.logging import get_logger
from ..db import repository as repo
from ..db import session_scope
from ..llm import ChatMessage, get_router

log = get_logger(__name__)


# ---------- Agent state ----------


class NutritionState(TypedDict, total=False):
    user_id: str
    user_message: str
    image_path: str | None

    food_result: dict[str, Any] | None
    meal_id: int | None
    history_summary: dict[str, Any] | None

    final_answer: str
    provider: str
    model: str


# ---------- MCP client lifecycle ----------


@asynccontextmanager
async def food_vlm_client(*, mock: bool = False) -> AsyncIterator[ClientSession]:
    project_root = Path(__file__).resolve().parents[3]
    server_args = ["-m", "backend.app.mcp_servers.food_vlm.server"]
    if mock:
        server_args.append("--mock")
    params = StdioServerParameters(
        command=sys.executable,
        args=server_args,
        env={**os.environ},
        cwd=str(project_root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# ---------- Nodes ----------


async def call_food_vlm_node(state: NutritionState) -> NutritionState:
    image = state.get("image_path")
    if not image:
        return {"food_result": None}

    async with food_vlm_client() as session:
        log.info("calling_food_vlm", image=image)
        result = await session.call_tool(
            "recognize_food",
            {"image": image, "hint": state.get("user_message", "")},
        )
        if result.isError:
            log.warning("food_vlm_error", content=str(result.content))
            return {"food_result": {"error": "tool failed"}}
        return {"food_result": result.structuredContent or {}}


async def persist_meal_node(state: NutritionState) -> NutritionState:
    """If food_result is valid, write a row into meals."""
    food = state.get("food_result")
    user_id = state.get("user_id", "demo-user")
    if not food or "items" not in food:
        return {"meal_id": None}

    async with session_scope() as s:
        # Make sure user exists (with sensible defaults; user can update later)
        await repo.upsert_user(s, user_id)
        m = await repo.add_meal(
            s,
            user_id,
            dishes=food.get("items", []),
            total_kcal=food.get("total_kcal", 0.0),
            total_protein_g=food.get("total_protein_g", 0.0),
            total_carbs_g=food.get("total_carbs_g", 0.0),
            total_fat_g=food.get("total_fat_g", 0.0),
            total_fiber_g=sum(i.get("fiber_g", 0) for i in food.get("items", [])),
            confidence=food.get("overall_confidence", 0.6),
            source="photo",
            image_path=state.get("image_path"),
            notes=food.get("notes", ""),
        )
        log.info("meal_persisted", meal_id=m.id, user_id=user_id, kcal=m.total_kcal)
        return {"meal_id": m.id}


async def fetch_history_node(state: NutritionState) -> NutritionState:
    """Pull the user's 7-day aggregate so the synthesizer can reference trends."""
    user_id = state.get("user_id", "demo-user")
    async with session_scope() as s:
        agg = await repo.aggregate_nutrition(s, user_id, days=7)
        profile = await repo.get_user(s, user_id)
        target_kcal = profile.target_kcal if profile else None
        goal = profile.goal if profile else None
    history = {
        "weekly_aggregate": agg,
        "profile": {"goal": goal, "target_kcal": target_kcal},
    }
    return {"history_summary": history}


async def synthesize_node(state: NutritionState) -> NutritionState:
    router = get_router()
    lf = get_langfuse()

    food = state.get("food_result")
    history = state.get("history_summary") or {}
    food_block = json.dumps(food, ensure_ascii=False, indent=2) if food else "(无图片)"
    history_block = json.dumps(history, ensure_ascii=False, indent=2)

    system = (
        "你是 HealthCoachAgent 营养教练（W2 demo 版）。"
        "你刚通过 MCP 工具拿到了：(1) 这一餐的食物识别结果；(2) 用户最近 7 天的营养汇总。"
        "请用 4-5 句话给用户一个友好、专业、含数据引用的营养评估，"
        "并结合用户目标（如 cut/bulk/maintenance）给出 1 条具体建议。"
    )
    user = (
        f"用户问题：{state.get('user_message', '请帮我看看这餐')}\n\n"
        f"=== 本餐识别结果 ===\n{food_block}\n\n"
        f"=== 用户画像 + 近 7 天汇总 ===\n{history_block}"
    )
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]

    if lf is not None:
        with lf.start_as_current_observation(
            name="nutrition_synthesize", as_type="generation"
        ) as gen:
            gen.update(input=[m.model_dump() for m in messages])
            resp = await router.chat("main_chat", messages, temperature=0.4)
            gen.update(
                output=resp.content,
                model=resp.model,
                metadata={"provider": resp.provider, "usage": resp.usage},
            )
    else:
        resp = await router.chat("main_chat", messages, temperature=0.4)

    return {
        "final_answer": resp.content,
        "provider": resp.provider,
        "model": resp.model,
    }


# ---------- Graph ----------


def build_nutrition_demo_graph():
    g: StateGraph = StateGraph(NutritionState)
    g.add_node("call_food_vlm", call_food_vlm_node)
    g.add_node("persist_meal", persist_meal_node)
    g.add_node("fetch_history", fetch_history_node)
    g.add_node("synthesize", synthesize_node)
    g.add_edge(START, "call_food_vlm")
    g.add_edge("call_food_vlm", "persist_meal")
    g.add_edge("persist_meal", "fetch_history")
    g.add_edge("fetch_history", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()
