"""LangGraph + MCP demo (W2 Day 2): identify food → save to DB → coach answer.

Pipeline:
  1. (food_vlm MCP) recognize_food         — 图片 → 结构化营养
  2. (health_db MCP) get_user_profile      — 拿用户目标/过敏
  3. (health_db MCP) add_meal              — 持久化这一餐
  4. (health_db MCP) aggregate_nutrition   — 取近 7 天总览（构造历史上下文）
  5. (LLM) synthesize                      — 综合给出教练建议（含历史对比）

Two MCP server subprocesses run in parallel; LangGraph spans them with
context managers. Each tool call traces in Langfuse if enabled.

Run:
    uv run python scripts/demo_nutrition_v2.py --image data/test_images/food.jpeg
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..core.langfuse_client import get_langfuse
from ..core.logging import get_logger
from ..llm import ChatMessage, get_router

log = get_logger(__name__)


# ---------- state ----------


class NutritionV2State(TypedDict, total=False):
    user_id: str
    user_message: str
    image_path: str | None

    # tool outputs
    food_result: dict[str, Any] | None
    user_profile: dict[str, Any] | None
    saved_meal: dict[str, Any] | None
    history_summary: dict[str, Any] | None

    # final
    final_answer: str
    provider: str
    model: str


# ---------- MCP client lifecycles ----------


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _stdio_params(server_module: str, *extra_args: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", server_module, *extra_args],
        env={**os.environ},
        cwd=str(PROJECT_ROOT),
    )


@asynccontextmanager
async def food_vlm_client(*, mock: bool = False) -> AsyncIterator[ClientSession]:
    args = ("--mock",) if mock else ()
    params = _stdio_params("backend.app.mcp_servers.food_vlm.server", *args)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield s


@asynccontextmanager
async def health_db_client() -> AsyncIterator[ClientSession]:
    params = _stdio_params("backend.app.mcp_servers.health_db.server")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield s


# ---------- nodes ----------


async def recognize_node(state: NutritionV2State) -> NutritionV2State:
    image = state.get("image_path")
    if not image:
        return {"food_result": None}

    async with food_vlm_client() as session:
        log.info("v2_calling_food_vlm", image=image)
        result = await session.call_tool(
            "recognize_food",
            {"image": image, "hint": state.get("user_message", "")},
        )
        if result.isError:
            log.warning("v2_food_vlm_error", content=str(result.content))
            return {"food_result": None}
        return {"food_result": result.structuredContent or {}}


async def db_io_node(state: NutritionV2State) -> NutritionV2State:
    """Combined DB calls: profile + add_meal + aggregate.

    Doing these in one MCP session avoids spawning the server 3 times.
    """
    user_id = state.get("user_id", "demo-user")
    food = state.get("food_result")

    profile: dict[str, Any] | None = None
    saved: dict[str, Any] | None = None
    history: dict[str, Any] | None = None

    async with health_db_client() as session:
        # 1. ensure user exists + load profile
        log.info("v2_db_upsert_user", user_id=user_id)
        await session.call_tool(
            "upsert_user_profile",
            {"user_id": user_id, "name": user_id},
        )
        prof_resp = await session.call_tool("get_user_profile", {"user_id": user_id})
        if not prof_resp.isError:
            profile = json.loads(prof_resp.content[0].text)

        # 2. persist this meal (only if we have a real recognition)
        if food and food.get("items"):
            args = {
                "user_id": user_id,
                "dishes": food.get("items", []),
                "total_kcal": food.get("total_kcal", 0.0),
                "total_protein_g": food.get("total_protein_g", 0.0),
                "total_carbs_g": food.get("total_carbs_g", 0.0),
                "total_fat_g": food.get("total_fat_g", 0.0),
                "total_fiber_g": sum(i.get("fiber_g", 0) for i in food.get("items", [])),
                "confidence": food.get("overall_confidence", 0.6),
                "source": "photo",
                "image_path": state.get("image_path"),
                "notes": food.get("notes", ""),
            }
            log.info("v2_db_add_meal", kcal=args["total_kcal"])
            meal_resp = await session.call_tool("add_meal", args)
            if not meal_resp.isError:
                saved = json.loads(meal_resp.content[0].text)

        # 3. aggregate last 7 days
        agg_resp = await session.call_tool(
            "aggregate_nutrition", {"user_id": user_id, "days": 7}
        )
        if not agg_resp.isError:
            history = json.loads(agg_resp.content[0].text)
            log.info(
                "v2_db_aggregate",
                meal_count=history.get("meal_count"),
                avg_kcal=history.get("avg_kcal_per_day"),
            )

    return {
        "user_profile": profile,
        "saved_meal": saved,
        "history_summary": history,
    }


async def synthesize_node(state: NutritionV2State) -> NutritionV2State:
    router = get_router()
    lf = get_langfuse()

    food = state.get("food_result")
    profile = state.get("user_profile") or {}
    history = state.get("history_summary") or {}

    food_block = (
        json.dumps(food, ensure_ascii=False, indent=2)
        if food
        else "(无图片，请仅基于文字回答)"
    )
    profile_block = json.dumps(
        {
            "goal": profile.get("goal", "maintenance"),
            "target_kcal": profile.get("target_kcal", 2000),
            "allergies": profile.get("allergies", []),
            "dislikes": profile.get("dislikes", []),
            "weight_kg": profile.get("weight_kg"),
        },
        ensure_ascii=False,
    )
    history_block = json.dumps(history, ensure_ascii=False)

    system = (
        "你是 HealthCoachAgent 营养教练（W2 Day2 版）。\n"
        "上游 MCP 工具刚刚:\n"
        "1) food_vlm 识别了用户当前这一餐\n"
        "2) health_db 给了你用户画像 + 近 7 天累计/日均营养摄入\n"
        "请基于这三块信息，用 4-5 句话给出含数字、含历史对比、贴合目标的反馈，"
        "结尾给一条具体可执行的下一步建议。"
        "如果用户有过敏/忌口，避开它们；如果近 7 天平均蛋白不足或超额，要明确指出。"
    )
    user = (
        f"用户问题：{state.get('user_message', '这餐怎么样？')}\n\n"
        f"=== 用户画像 ===\n{profile_block}\n\n"
        f"=== 当前这一餐（food_vlm） ===\n{food_block}\n\n"
        f"=== 近 7 天累计/日均（health_db.aggregate_nutrition） ===\n{history_block}"
    )
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]

    if lf is not None:
        with lf.start_as_current_observation(
            name="nutrition_v2_synthesize", as_type="generation"
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


# ---------- graph ----------


def build_nutrition_v2_graph():
    g: StateGraph = StateGraph(NutritionV2State)
    g.add_node("recognize", recognize_node)
    g.add_node("db_io", db_io_node)
    g.add_node("synthesize", synthesize_node)
    g.add_edge(START, "recognize")
    g.add_edge("recognize", "db_io")
    g.add_edge("db_io", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()
