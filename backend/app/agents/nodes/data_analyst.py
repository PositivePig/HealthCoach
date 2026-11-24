"""Data Analyst node (W4 D2).

Inputs from AgentState:
  - user_id, user_message
  - context (optional, from prior coaches)

Pipeline:
  1. Query health_db for recent data (meals 30d, activities 30d, vitals 30d)
  2. Generate trend charts (matplotlib) → save to data/charts/
  3. Optionally run execute_safe_sql for custom queries
  4. LLM synthesizes insights with data references
  5. Emit CoachAnswer + visited_coaches=['data']
  6. Parse handoff (e.g., user asks "怎么改善" → handoff to nutrition/fitness)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from langgraph.types import Command

from ...core.langfuse_client import get_langfuse
from ...core.logging import get_logger
from ...db import session_scope
from ...db import repository as repo
from ...llm import ChatMessage, get_router
from ...llm.types import ProviderError
from ...memory import get_memory_context  # 导入记忆系统
from ..state import AgentState, CoachAnswer

# Use non-interactive backend for matplotlib
matplotlib.use("Agg")

log = get_logger(__name__)

# Chart output directory
CHART_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "charts")
os.makedirs(CHART_DIR, exist_ok=True)


# ---- handoff triggers ----

# Keywords suggesting the user wants actionable advice (→ handoff to domain coach)
_HANDOFF_NUTRITION_KW = re.compile(
    r"(怎么吃|吃什么|饮食建议|营养方案|如何改善.*营养|餐单|食谱)", re.I
)
_HANDOFF_FITNESS_KW = re.compile(
    r"(怎么练|训练计划|运动方案|如何改善.*运动|锻炼建议|健身计划)", re.I
)
_HANDOFF_MENTAL_KW = re.compile(
    r"(情绪低落|压力大|失眠|焦虑|心情不好|心理健康)", re.I
)


DATA_ANALYST_PROMPT = """你是 HealthCoachAgent 的数据分析师 Coach。

你的任务：基于下面提供的 (a) 用户画像 (b) 近期健康数据 (c) 生成的图表路径，
对用户的问题给出**数据驱动、有具体数字、可操作**的回答。

要求：
- 中文，专业但友好，不超过 6 句话
- 至少包含 2 条具体数字（来自实际数据）
- 如果有关键趋势（上升/下降/异常），明确指出
- 不编造数字；不诊断疾病
- 若用户问"怎么改善/怎么办"，最后追加一行：HANDOFF: <coach>
  （可选值：nutrition / fitness / mental）
- 若只是数据查询/趋势分析，不添加 HANDOFF
"""

# ---- chart generators ----


def _generate_weight_chart(user_id: str, vitals: list[Any], days: int = 30) -> str | None:
    """Generate weight trend chart. Returns file path or None."""
    if not vitals:
        return None
    # Filter valid weight entries
    data = [(v.ts, v.weight_kg) for v in vitals if v.weight_kg is not None]
    if len(data) < 2:
        return None
    data.sort(key=lambda x: x[0])
    dates = [d[0] for d in data]
    weights = [d[1] for d in data]

    plt.figure(figsize=(10, 4))
    plt.plot(dates, weights, marker="o", linestyle="-", color="#4A90D9", linewidth=2)
    plt.xlabel("日期")
    plt.ylabel("体重 (kg)")
    plt.title(f"体重趋势（最近 {len(data)} 条记录）")
    plt.xticks(rotation=45)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    filepath = os.path.join(CHART_DIR, f"{user_id}_weight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    plt.savefig(filepath, dpi=100)
    plt.close()
    return filepath


def _generate_calorie_chart(user_id: str, meals: list[Any], days: int = 30) -> str | None:
    """Generate daily calorie chart. Returns file path or None."""
    if not meals:
        return None
    # Aggregate by date
    daily: dict[str, float] = {}
    for m in meals:
        date_key = m.ts.strftime("%Y-%m-%d")
        daily[date_key] = daily.get(date_key, 0) + (m.total_kcal or 0)

    if not daily:
        return None

    sorted_dates = sorted(daily.keys())
    calories = [daily[d] for d in sorted_dates]

    plt.figure(figsize=(10, 4))
    plt.bar(sorted_dates, calories, color="#50C878", alpha=0.7)
    plt.xlabel("日期")
    plt.ylabel("热量 (kcal)")
    plt.title(f"每日热量摄入（最近 {len(sorted_dates)} 天）")
    plt.xticks(rotation=45)
    plt.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()

    filepath = os.path.join(CHART_DIR, f"{user_id}_calories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    plt.savefig(filepath, dpi=100)
    plt.close()
    return filepath


def _generate_sleep_chart(user_id: str, vitals: list[Any], days: int = 30) -> str | None:
    """Generate sleep duration chart. Returns file path or None."""
    if not vitals:
        return None
    data = [(v.ts, v.sleep_min) for v in vitals if v.sleep_min is not None]
    if len(data) < 2:
        return None
    data.sort(key=lambda x: x[0])
    dates = [d[0] for d in data]
    sleep_hours = [d[1] / 60 for d in data]  # convert min → hours

    plt.figure(figsize=(10, 4))
    plt.plot(dates, sleep_hours, marker="s", linestyle="-", color="#9B59B6", linewidth=2)
    plt.axhline(y=7, color="r", linestyle="--", alpha=0.5, label="推荐 7h")
    plt.xlabel("日期")
    plt.ylabel("睡眠时长 (h)")
    plt.title(f"睡眠时长趋势（最近 {len(data)} 条记录）")
    plt.xticks(rotation=45)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    filepath = os.path.join(CHART_DIR, f"{user_id}_sleep_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    plt.savefig(filepath, dpi=100)
    plt.close()
    return filepath


def _generate_activity_chart(user_id: str, activities: list[Any], days: int = 30) -> str | None:
    """Generate activity duration pie/bar chart. Returns file path or None."""
    if not activities:
        return None
    from collections import Counter

    type_counts = Counter(a.type for a in activities)
    if not type_counts:
        return None

    labels = list(type_counts.keys())
    sizes = list(type_counts.values())

    plt.figure(figsize=(8, 5))
    plt.bar(labels, sizes, color="#E67E22", alpha=0.7)
    plt.xlabel("运动类型")
    plt.ylabel("次数")
    plt.title(f"运动类型分布（最近 {len(activities)} 次）")
    plt.xticks(rotation=30)
    plt.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()

    filepath = os.path.join(CHART_DIR, f"{user_id}_activity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    plt.savefig(filepath, dpi=100)
    plt.close()
    return filepath


async def data_analyst_node(state: AgentState) -> Command[Any]:
    user_id = state.get("user_id", "anon")
    user_msg = state.get("user_message", "") or ""

    # ---- 1. fetch data from health_db + memory context ----
    profile_block = "（暂无用户画像）"
    meals_block = "（近 30 天无用餐记录）"
    activities_block = "（近 30 天无运动记录）"
    vitals_block = "（近 30 天无体征数据）"
    memory_block = "（暂无记忆上下文）"
    chart_paths: list[str] = []

    profile_dict: dict[str, Any] = {}
    meals: list[Any] = []
    activities: list[Any] = []
    vitals: list[Any] = []

    try:
        async with session_scope() as session:
            # Profile
            user = await repo.get_user(session, user_id)
            if user:
                profile_dict = {
                    "goal": user.goal,
                    "target_kcal": user.target_kcal,
                    "weight_kg": user.weight_kg,
                    "target_weight": user.target_weight,
                }
                profile_block = (
                    f"目标 {user.goal} / 目标体重 {user.target_weight or '未设'}kg / "
                    f"当前体重 {user.weight_kg}kg"
                )

            # Meals (30d)
            meals = await repo.query_meals(session, user_id, days=30)
            if meals:
                total_kcal = sum(m.total_kcal or 0 for m in meals)
                avg_kcal = round(total_kcal / 30, 0)
                meals_block = (
                    f"近 30 天 {len(meals)} 餐，总热量 {total_kcal} kcal，"
                    f"日均约 {avg_kcal} kcal"
                )

            # Activities (30d)
            activities = await repo.query_activities(session, user_id, days=30)
            if activities:
                total_min = sum(a.duration_min or 0 for a in activities)
                types = ", ".join(set(a.type for a in activities))
                activities_block = (
                    f"近 30 天 {len(activities)} 次运动，总时长 {total_min} 分钟，"
                    f"类型：{types}"
                )

            # Vitals (30d)
            vitals = await repo.query_vitals(session, user_id, days=30)
            if vitals:
                weight_vals = [v.weight_kg for v in vitals if v.weight_kg is not None]
                sleep_vals = [v.sleep_min for v in vitals if v.sleep_min is not None]
                hrv_vals = [v.hrv_ms for v in vitals if v.hrv_ms is not None]

            # 获取记忆上下文（三层记忆系统）
            try:
                memory_ctx = await get_memory_context(
                    user_id=user_id,
                    session=session,
                    query=user_msg,
                    episodic_days=30,  # 数据分析看 30 天
                    semantic_k=5,
                )
                memory_block = memory_ctx.format_for_prompt()
            except Exception as mem_err:  # noqa: BLE001
                log.warning("memory_context_failed", error=str(mem_err))
                memory_block = "（记忆上下文获取失败）"
                parts = []
                if weight_vals:
                    parts.append(f"体重记录 {len(weight_vals)} 条，最新 {weight_vals[-1]} kg")
                if sleep_vals:
                    avg_sleep = round(sum(sleep_vals) / len(sleep_vals) / 60, 1)
                    parts.append(f"平均睡眠 {avg_sleep} h")
                if hrv_vals:
                    avg_hrv = round(sum(hrv_vals) / len(hrv_vals), 0)
                    parts.append(f"平均 HRV {avg_hrv} ms")
                vitals_block = "; ".join(parts)

        # ---- 2. generate charts ----
        if vitals:
            path = _generate_weight_chart(user_id, vitals)
            if path:
                chart_paths.append(path)
            path = _generate_sleep_chart(user_id, vitals)
            if path:
                chart_paths.append(path)
        if meals:
            path = _generate_calorie_chart(user_id, meals)
            if path:
                chart_paths.append(path)
        if activities:
            path = _generate_activity_chart(user_id, activities)
            if path:
                chart_paths.append(path)

    except Exception as e:  # noqa: BLE001
        log.warning("data_analyst_load_failed", error=str(e))

    # ---- 3. format chart references ----
    chart_block = "（未生成图表）"
    if chart_paths:
        chart_lines = [f"  - {os.path.basename(p)}" for p in chart_paths]
        chart_block = "已生成图表：\n" + "\n".join(chart_lines)

    # ---- 4. LLM synthesis ----
    user_payload = (
        f"[记忆上下文]\n{memory_block}\n\n"
        f"[用户画像]\n{profile_block}\n\n"
        f"[用餐数据]\n{meals_block}\n\n"
        f"[运动数据]\n{activities_block}\n\n"
        f"[体征数据]\n{vitals_block}\n\n"
        f"[图表]\n{chart_block}\n\n"
        f"[用户问题]\n{user_msg or '（请对最近 30 天数据做趋势分析）'}"
    )

    router = get_router()
    lf = get_langfuse()
    answer_text = ""
    provider, model = "", ""

    messages = [
        ChatMessage(role="system", content=DATA_ANALYST_PROMPT),
        ChatMessage(role="user", content=user_payload),
    ]
    try:
        if lf is not None:
            with lf.start_as_current_observation(
                name="data_analyst", as_type="generation"
            ) as gen:
                gen.update(input=[m.model_dump() for m in messages])
                resp = await router.chat("main_chat", messages, temperature=0.3, max_tokens=500)
                gen.update(
                    output=resp.content, model=resp.model,
                    metadata={"provider": resp.provider, "user_id": user_id},
                )
        else:
            resp = await router.chat("main_chat", messages, temperature=0.3, max_tokens=500)
        answer_text = resp.content
        provider, model = resp.provider, resp.model
    except ProviderError as e:
        log.warning("data_analyst_llm_failed", error=str(e))
        answer_text = "[fallback] 数据已获取，但模型暂时不可用，请稍后重试。"

    # ---- 5. parse handoff ----
    handoff: str | None = None
    text = answer_text
    m = re.search(r"HANDOFF:\s*(\w+)", answer_text, flags=re.I)
    if m:
        cand = m.group(1).lower()
        if cand and cand != "data":  # prevent self-handoff
            handoff = cand
        text = re.sub(r"HANDOFF:\s*\w+\s*$", "", answer_text, flags=re.I).strip()
    else:
        # Keyword-based handoff
        if _HANDOFF_NUTRITION_KW.search(user_msg):
            handoff = "nutrition"
        elif _HANDOFF_FITNESS_KW.search(user_msg):
            handoff = "fitness"
        elif _HANDOFF_MENTAL_KW.search(user_msg):
            handoff = "mental"

    coach_answer: CoachAnswer = {
        "coach": "data",
        "text": text,
        "citations": [],  # Data analyst uses charts, not text citations
        "metadata": {
            "provider": provider,
            "model": model,
            "chart_paths": chart_paths,
            "had_profile": bool(profile_dict),
        },
    }

    log.info(
        "data_analyst_done",
        chart_count=len(chart_paths), handoff=handoff,
    )

    return Command(
        update={
            "coach_answers": [coach_answer],
            "visited_coaches": ["data"],
            "handoff_to": handoff,
        },
        goto="supervisor",
    )
