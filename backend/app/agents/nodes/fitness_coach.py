"""Fitness Coach node (W3 D2).

Inputs from AgentState:
  - user_id, user_message
  - context.user_profile (optional)
  - any prior CoachAnswer in coach_answers (e.g. nutrition handed off)

Pipeline:
  1. fetch user profile + recent 14-day activity stats + 30-day vitals(sleep/HRV)
  2. detect injury/safety red-flag keywords; if matched, force a safety hit
  3. RAG over the fitness corpus with (msg + goal + recent activity types)
     - bias toward tag filter when injury / 跑步 / 力量 / hiit detected
  4. LLM synthesizes a coach-style answer with citations + handoff hint
  5. emit CoachAnswer + visited_coaches=['fitness']
  6. parse handoff (e.g., 模型说"营养上要注意…" → handoff: nutrition)

Bidirectional handoff:
  Supervisor only allows each coach once per turn (loop guard depth=2),
  so nutrition→fitness or fitness→nutrition is supported but they cannot
  ping-pong. Direction is decided by:
    - explicit "HANDOFF: <coach>" trailer printed by the LLM, OR
    - keyword fallback (营养/吃/餐 → nutrition).
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from ...core.langfuse_client import get_langfuse
from ...core.logging import get_logger
from ...db import session_scope
from ...db import repository as repo
from ...llm import ChatMessage, get_router
from ...llm.types import ProviderError
from ...rag import BM25Retriever, format_citations
from ...rag.seeds.fitness_seed import build_fitness_corpus
from ...memory import get_memory_context  # 导入记忆系统
from ..state import AgentState, CoachAnswer

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_fitness_retriever() -> BM25Retriever:
    return BM25Retriever(build_fitness_corpus())


# ---- triggers ----

# When these appear, we want at least one citation tagged "safety" or "recovery".
_RED_FLAGS = re.compile(
    r"(胸痛|胸闷|压榨|晕厥|晕倒|放射痛|麻木|发麻|头晕|手脚发麻|大小便失禁|"
    r"剧痛|严重疼|无法行走|喘不过气|呼吸困难)"
)
_INJURY_KW = re.compile(
    r"(膝盖痛|膝痛|腰痛|下背痛|背痛|肩痛|脚踝|崴|拉伤|扭伤|拉伸不开|"
    r"酸痛.{0,4}天|连续.{0,2}天.{0,2}痛|髌|筋膜|网球肘)"
)
_RUNNING_KW = re.compile(r"(跑步|跑了|配速|步频|马拉松|5K|10K|公里)")
_STRENGTH_KW = re.compile(r"(深蹲|硬拉|卧推|引体|举铁|力量|增肌|肌肥大|RM|组数)")
_HIIT_KW = re.compile(r"(HIIT|TABATA|高强度间歇)", re.I)

# Reverse handoff triggers: "fitness → nutrition"
_HANDOFF_NUTRITION_KW = re.compile(
    r"(吃什么|怎么吃|蛋白|碳水|餐|饮食|加餐|食谱|营养)"
)


def _pick_tag_filter(user_msg: str) -> str | None:
    """Bias retrieval to the most relevant tag, if any."""
    if _RED_FLAGS.search(user_msg):
        return "safety"
    if _INJURY_KW.search(user_msg):
        return "recovery"
    if _HIIT_KW.search(user_msg):
        return "cardio"
    if _RUNNING_KW.search(user_msg):
        return "running"
    if _STRENGTH_KW.search(user_msg):
        return "strength"
    return None


FITNESS_PROMPT = """你是 HealthCoachAgent 的注册体能 / 运动表现 Coach（ACSM-CPT 风格）。

任务：基于下面提供的 (a) 用户画像 (b) 最近 14 天运动数据 (c) 最近睡眠/HRV
(d) 知识库引用片段，对用户的问题给出**可执行、剂量明确、安全优先**的回答。

要求：
- 中文，自然友好，**不超过 6 句话**
- 至少包含一条具体数字（用户实际数据 或 知识库引用）
- 在回答末尾用 (id1, id2) 形式标出引用到的 doc id（来自下面的 [refs]）
- 不编造数字；不诊断；不开处方
- 若 [refs] 中包含 safety 标签的红线引用，**必须**把该建议放在第一句
- 若需要营养配合（蛋白量/补糖/补水时机等），最后追加一行：HANDOFF: nutrition（只允许 nutrition/fitness/mental/data）
- 严禁向 fitness 自身 handoff
"""


async def fitness_coach_node(state: AgentState) -> Command[Any]:
    user_id = state.get("user_id", "anon")
    user_msg = state.get("user_message", "") or ""

    # ---- 1. profile + recent activity + vitals + memory context ----
    profile_block = "（暂无用户画像）"
    activity_block = "（近 14 天无运动记录）"
    vital_block = "（近 30 天无体征数据）"
    memory_block = "（暂无记忆上下文）"
    profile_dict: dict[str, Any] = {}
    activity_kinds: list[str] = []
    weekly_minutes = 0.0
    try:
        async with session_scope() as session:
            user = await repo.get_user(session, user_id)
            if user:
                profile_dict = {
                    "goal": user.goal,
                    "weight_kg": user.weight_kg,
                    "diseases": user.diseases,
                }
                profile_block = (
                    f"目标 {user.goal} / 体重 {user.weight_kg}kg / "
                    f"病史 {user.diseases or '无'}"
                )
            acts = await repo.query_activities(session, user_id, days=14)
            if acts:
                kinds = Counter(a.type for a in acts)
                activity_kinds = list(kinds)
                total_min = sum(a.duration_min for a in acts)
                weekly_minutes = round(total_min / 2, 1)
                top = ", ".join(f"{k}×{v}" for k, v in kinds.most_common(3))
                activity_block = (
                    f"14 天 {len(acts)} 次训练（折合周 {weekly_minutes} 分钟）；"
                    f"主项：{top}。最近一次：{acts[0].type} {acts[0].duration_min} 分钟,"
                    f" 强度 {acts[0].intensity}."
                )
            vits = await repo.query_vitals(session, user_id, days=30)
            if vits:
                # average sleep / hrv where available
                sleep_vals = [v.sleep_min for v in vits if v.sleep_min is not None]
                hrv_vals = [v.hrv_ms for v in vits if v.hrv_ms is not None]
                parts = []
                if sleep_vals:
                    avg_sleep = round(sum(sleep_vals) / len(sleep_vals) / 60, 1)
                    parts.append(f"平均睡眠 {avg_sleep}h ({len(sleep_vals)} 次记录)")
                if hrv_vals:
                    avg_hrv = round(sum(hrv_vals) / len(hrv_vals), 0)
                    parts.append(f"平均 HRV {avg_hrv} ms")
                if parts:
                    vital_block = "; ".join(parts)
            # 获取记忆上下文（三层记忆系统）
            try:
                memory_ctx = await get_memory_context(
                    user_id=user_id,
                    session=session,
                    query=user_msg,
                    episodic_days=14,  # 运动数据看 14 天
                    semantic_k=5,
                )
                memory_block = memory_ctx.format_for_prompt()
            except Exception as mem_err:  # noqa: BLE001
                log.warning("memory_context_failed", error=str(mem_err))
                memory_block = "（记忆上下文获取失败）"
    except Exception as e:  # noqa: BLE001
        log.warning("fitness_profile_load_failed", error=str(e))

    # ---- 2. RAG with optional tag filter ----
    rag = get_fitness_retriever()
    tag_filter = _pick_tag_filter(user_msg)
    rag_query_parts = [user_msg]
    if profile_dict.get("goal"):
        rag_query_parts.append(profile_dict["goal"])
    if activity_kinds:
        rag_query_parts.extend(activity_kinds[:3])
    rag_query = " ".join(rag_query_parts).strip() or "运动训练"
    
    # 先尝试带tag过滤的检索
    hits = rag.search(rag_query, k=4, tag_filter=tag_filter)
    # If a tag filter dropped everything, fall back to global top-k.
    if not hits:
        hits = rag.search(rag_query, k=4)
    
    # 后过滤：如果问题不匹配红线关键词，但检索到了redline标签的文档，移除它们
    # 这避免"肌肉酸痛"等问题误触发safety_first模式
    if not _RED_FLAGS.search(user_msg):
        hits = [h for h in hits if "redline" not in h.doc.tags]
        # 如果过滤后数量不足，补充非redline文档
        if len(hits) < 4:
            extra = [h for h in rag.search(rag_query, k=8) 
                     if "redline" not in h.doc.tags and h not in hits]
            hits.extend(extra[:4 - len(hits)])
    citations = format_citations(hits)
    refs_block = "\n".join(f"  - {c['id']}: {c['quote']}" for c in citations) or "（无引用）"

    # ---- 3. LLM ----
    user_payload = (
        f"[记忆上下文]\n{memory_block}\n\n"
        f"[用户画像]\n{profile_block}\n\n"
        f"[最近运动]\n{activity_block}\n\n"
        f"[最近体征]\n{vital_block}\n\n"
        f"[refs]\n{refs_block}\n\n"
        f"[用户问题]\n{user_msg or '（请基于以上给出训练评估与下一步）'}"
    )

    router = get_router()
    lf = get_langfuse()
    answer_text = ""
    provider, model = "", ""
    messages = [
        ChatMessage(role="system", content=FITNESS_PROMPT),
        ChatMessage(role="user", content=user_payload),
    ]
    try:
        if lf is not None:
            with lf.start_as_current_observation(
                name="fitness_coach", as_type="generation"
            ) as gen:
                gen.update(input=[m.model_dump() for m in messages])
                resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=400)
                gen.update(
                    output=resp.content, model=resp.model,
                    metadata={"provider": resp.provider, "user_id": user_id,
                              "tag_filter": tag_filter},
                )
        else:
            resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=400)
        answer_text = resp.content
        provider, model = resp.provider, resp.model
    except ProviderError as e:
        log.warning("fitness_llm_failed", error=str(e))
        answer_text = (
            "[fallback] 无法连接到模型；建议参考下方引用做基线决策。"
        )

    # ---- 4. parse handoff ----
    handoff: str | None = None
    text = answer_text
    m = re.search(r"HANDOFF:\s*(\w+)", answer_text, flags=re.I)
    if m:
        cand = m.group(1).lower()
        valid = {"nutrition", "fitness", "mental", "data"}
        # Guard against self-handoff loops + invalid targets.
        if cand and cand != "fitness" and cand in valid:
            handoff = cand
        elif cand and cand not in valid:
            log.warning("fitness_handoff_invalid", raw=cand, mapped_to="nutrition")
            handoff = "nutrition"  # safe fallback
        text = re.sub(r"HANDOFF:\s*\w+\s*$", "", answer_text, flags=re.I).strip()
    elif _HANDOFF_NUTRITION_KW.search(user_msg):
        handoff = "nutrition"

    coach_answer: CoachAnswer = {
        "coach": "fitness",
        "text": text,
        "citations": citations,
        "metadata": {
            "provider": provider,
            "model": model,
            "rag_hits": len(citations),
            "tag_filter": tag_filter,
            "weekly_minutes": weekly_minutes,
            "had_profile": bool(profile_dict),
        },
    }

    log.info(
        "fitness_coach_done",
        rag_hits=len(citations), tag_filter=tag_filter, handoff=handoff,
    )

    return Command(
        update={
            "coach_answers": [coach_answer],
            "visited_coaches": ["fitness"],
            "handoff_to": handoff,
        },
        goto="supervisor",
    )
