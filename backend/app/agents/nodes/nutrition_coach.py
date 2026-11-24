"""Nutrition Coach node.

Inputs from AgentState:
  - user_id, user_message, image_path
  - context.user_profile (set by data layer if available)
  - context.recent_meals (set by data layer or coach itself)

Pipeline:
  1. (if image) call food_vlm via in-process recognizer (cheaper than MCP subprocess in v1)
  2. fetch user profile + recent 7-day nutrition aggregate via repository
  3. RAG query over nutrition corpus with the user's question + profile facts
  4. LLM synthesizes a coach-style answer with citations
  5. emit a CoachAnswer + visited_coaches=['nutrition']
  6. decide handoff (e.g., user mentioned 跑步/训练 → fitness)
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from ...core.langfuse_client import get_langfuse
from ...core.logging import get_logger
from ...db import session_scope
from ...db import repository as repo
from ...llm import ChatMessage, get_router
from ...llm.types import ProviderError
from ...mcp_servers.food_vlm.recognizer import FoodRecognizer
from ...rag import BM25Retriever, format_citations
from ...rag.seeds.nutrition_seed import build_nutrition_corpus
from ...memory import get_memory_context  # 导入记忆系统
from ..state import AgentState, CoachAnswer

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_nutrition_retriever() -> BM25Retriever:
    return BM25Retriever(build_nutrition_corpus())


_HANDOFF_FITNESS = re.compile(
    r"(刚跑|跑了|刚练|练完|训练后|举铁|健身|HIIT|有氧|拉伸)", re.I
)


NUTRITION_PROMPT = """你是 HealthCoachAgent 的注册营养师 Coach。

你的任务：基于下面提供的 (a) 用户画像 (b) 最近营养数据 (c) 食物识别结果（如有）
(d) 知识库引用片段，对用户的问题给出**准确、有数据支撑、可执行**的回答。

要求：
- 中文，自然友好，不超过 5 句话
- 至少包含一条具体数字（用户实际数据 或 知识库引用）
- 在回答末尾用 (id1, id2) 形式标出引用到的 doc id（来自下面的 [refs]）
- 不编造数字；不诊断疾病；不给医疗建议
- 若用户提到"训练/运动/跑步"等，最后追加一行：HANDOFF: fitness（只允许 fitness/nutrition/mental/data）
"""


async def nutrition_coach_node(state: AgentState) -> Command[Any]:
    user_id = state.get("user_id", "anon")
    user_msg = state.get("user_message", "") or ""
    image_path = state.get("image_path")

    # ---- 1. optional vision ----
    food_block = "（无图片）"
    food_data: dict | None = None
    if image_path:
        recognizer = FoodRecognizer()
        try:
            res = await recognizer.recognize(image_path, hint=user_msg)
            food_data = res.model_dump()
            food_block = (
                f"识别到 {len(res.items)} 个食材：" +
                ", ".join(i.name for i in res.items) +
                f"。总能量 {res.total_kcal} kcal / 蛋白 {res.total_protein_g}g "
                f"/ 碳水 {res.total_carbs_g}g / 脂肪 {res.total_fat_g}g。"
                f" 备注：{res.notes}"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("nutrition_vision_failed", error=str(e))
            food_block = f"（图片识别失败：{e}）"

    # ---- 2. user profile + recent stats + memory context ----
    profile_block = "（暂无用户画像）"
    stats_block = "（暂无近 7 天数据）"
    profile_dict: dict[str, Any] = {}
    memory_block = "（暂无记忆上下文）"
    try:
        async with session_scope() as session:
            user = await repo.get_user(session, user_id)
            if user:
                profile_dict = {
                    "goal": user.goal,
                    "target_kcal": user.target_kcal,
                    "weight_kg": user.weight_kg,
                    "allergies": user.allergies,
                    "diseases": user.diseases,
                }
                profile_block = (
                    f"目标 {user.goal} / target_kcal {user.target_kcal} / "
                    f"体重 {user.weight_kg}kg / 过敏 {user.allergies or '无'} / "
                    f"病史 {user.diseases or '无'}"
                )
            agg = await repo.aggregate_nutrition(session, user_id, days=7)
            stats_block = (
                f"近 7 天: 餐次 {agg['meal_count']}, "
                f"日均 kcal {agg['avg_kcal_per_day']}, "
                f"日均蛋白 {agg['avg_protein_per_day']}g, "
                f"日均碳水 {agg['avg_carbs_per_day']}g, "
                f"日均脂肪 {agg['avg_fat_per_day']}g"
            )
            # 获取记忆上下文（三层记忆系统）
            try:
                memory_ctx = await get_memory_context(
                    user_id=user_id,
                    session=session,
                    query=user_msg,
                    episodic_days=7,
                    semantic_k=5,
                )
                memory_block = memory_ctx.format_for_prompt()
            except Exception as mem_err:  # noqa: BLE001
                log.warning("memory_context_failed", error=str(mem_err))
                memory_block = "（记忆上下文获取失败）"
    except Exception as e:  # noqa: BLE001
        log.warning("nutrition_profile_load_failed", error=str(e))

    # ---- 3. RAG ----
    rag = get_nutrition_retriever()
    # Combine user msg + profile keywords + identified food names for retrieval
    rag_query_parts = [user_msg]
    if profile_dict.get("goal"):
        rag_query_parts.append(profile_dict["goal"])
    if food_data:
        rag_query_parts.extend(i["name"] for i in food_data.get("items", []))
    rag_query = " ".join(rag_query_parts).strip() or "营养建议"
    hits = rag.search(rag_query, k=4)
    citations = format_citations(hits)
    refs_block = "\n".join(
        f"  - {c['id']}: {c['quote']}" for c in citations
    ) or "（无相关引用）"

    # ---- 4. LLM synth ----
    user_payload = (
        f"[记忆上下文]\n{memory_block}\n\n"
        f"[用户画像]\n{profile_block}\n\n"
        f"[最近数据]\n{stats_block}\n\n"
        f"[食物识别]\n{food_block}\n\n"
        f"[refs]\n{refs_block}\n\n"
        f"[用户问题]\n{user_msg or '（用户未提问，请基于以上给出营养评估）'}"
    )

    router = get_router()
    lf = get_langfuse()
    answer_text = ""
    provider = ""
    model = ""

    messages = [
        ChatMessage(role="system", content=NUTRITION_PROMPT),
        ChatMessage(role="user", content=user_payload),
    ]
    try:
        if lf is not None:
            with lf.start_as_current_observation(
                name="nutrition_coach", as_type="generation"
            ) as gen:
                gen.update(input=[m.model_dump() for m in messages])
                resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=400)
                gen.update(
                    output=resp.content, model=resp.model,
                    metadata={"provider": resp.provider, "user_id": user_id},
                )
        else:
            resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=400)
        answer_text = resp.content
        provider, model = resp.provider, resp.model
    except ProviderError as e:
        log.warning("nutrition_llm_failed", error=str(e))
        answer_text = (
            f"[fallback] 已识别 {food_block}。建议参考引用规则。"
        )

    # ---- 5. parse handoff suffix (model may print "HANDOFF: fitness") ----
    handoff: str | None = None
    text = answer_text
    m = re.search(r"HANDOFF:\s*(\w+)", answer_text, flags=re.I)
    if m:
        raw = m.group(1).lower()
        # Validate: only allow known coach names
        if raw in ("nutrition", "fitness", "mental", "data"):
            handoff = raw
        else:
            log.warning("nutrition_handoff_invalid", raw=raw, mapped_to="fitness")
            handoff = "fitness"  # safe fallback
        text = re.sub(r"HANDOFF:\s*\w+\s*$", "", answer_text, flags=re.I).strip()
    elif _HANDOFF_FITNESS.search(user_msg):
        handoff = "fitness"

    coach_answer: CoachAnswer = {
        "coach": "nutrition",
        "text": text,
        "citations": citations,
        "metadata": {
            "provider": provider,
            "model": model,
            "rag_hits": len(citations),
            "had_image": bool(image_path),
            "had_profile": bool(profile_dict),
        },
    }

    log.info(
        "nutrition_coach_done",
        rag_hits=len(citations), had_image=bool(image_path), handoff=handoff,
    )

    return Command(
        update={
            "coach_answers": [coach_answer],
            "visited_coaches": ["nutrition"],
            "handoff_to": handoff,
        },
        goto="supervisor",
    )
