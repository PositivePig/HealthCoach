"""Mental Coach node (W4 D1).

Inputs from AgentState:
  - user_id, user_message
  - context.user_profile (optional)
  - any prior CoachAnswer in coach_answers (e.g. nutrition handed off)

Pipeline:
  1. detect crisis/redline keywords (self-harm, suicide, severe depression)
     → if matched, return crisis response immediately (no LLM call)
  2. fetch user profile (goal, recent mood/sleep trends if available)
  3. RAG over the mental health corpus with tag filter
  4. LLM synthesizes a coach-style answer with citations + handoff hint
  5. emit CoachAnswer + visited_coaches=['mental']
  6. parse handoff (e.g., model says "运动可以缓解..." → handoff: fitness)

Bidirectional handoff:
  - mental → nutrition: when user asks about nutrition for mood (Omega-3, gut-brain)
  - mental → fitness: when user asks about exercise for anxiety/depression
  - Self-handoff prevention: model is instructed to never handoff to 'mental'
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from ...core.langfuse_client import get_langfuse
from ...core.logging import get_logger
from ...llm import ChatMessage, get_router
from ...llm.types import ProviderError
from ...rag import BM25Retriever, format_citations
from ...rag.seeds.mental_seed import build_mental_corpus
from ...memory import get_memory_context  # 导入记忆系统
from ..state import AgentState, CoachAnswer

log = get_logger(__name__)

# db imports – may fail in pure-rag tests; guard with conditional import.
try:
    from ...db import session_scope
    from ...db import repository as repo
except Exception:  # noqa: BLE001
    session_scope = None  # type: ignore[assignment]
    repo = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def get_mental_retriever() -> BM25Retriever:
    return BM25Retriever(build_mental_corpus())


# ---- crisis / redline detection ----

_REDLINE_KW = re.compile(
    r"(自伤|自残|割腕|撞击|烧伤|烫伤|不想活|自杀|轻生|结束生命|"
    r"跳楼|跳河|服药过量|割腕自杀|活不下去|没有意义|没意义|"
    r"绝望.{0,5}死|想死|去死|杀死自己|了断自己|"
    r"想放弃生命|活着没意思|不如死了)"
)

_SEVERE_DEPRESSION_KW = re.compile(
    r"(无法起床|连续.{0,5}天不进食|完全失去兴趣|整天躺着|不想动弹|"
    r"2周.{0,10}(不洗脸|不刷牙|不洗澡))"
)

_PANIC_KW = re.compile(
    r"(心跳加速|心悸.{0,5}窒息|胸闷.{0,5}头晕|突然.{0,5}恐惧|感觉要死了|"
    r"惊恐.{0,5}发作)"
)

# ---- tag filter triggers ----

_SLEEP_KW = re.compile(r"(睡眠|失眠|熬夜|早醒|睡眠质量|深睡眠|REM)")
_STRESS_KW = re.compile(r"(压力|焦虑|紧张| burnout|崩溃|烦躁|易怒|工作压力大)")
_ANXIETY_KW = re.compile(r"(焦虑|惊恐|恐慌|紧张.{0,5}不安|担心.{0,10}发生)")
_DEPRESSION_KW = re.compile(r"(抑郁|低落|无兴趣|无动力|悲伤|绝望|提不起劲)")
_SOCIAL_KW = re.compile(r"(孤独|孤立|社交|人际关系|冲突|吵架)")

# ---- handoff triggers ----

_HANDOFF_NUTRITION_KW = re.compile(
    r"(吃什么|营养|Omega.{0,2}3|深海鱼|色氨酸|益生菌|肠道|发酵食品)"
)

_HANDOFF_FITNESS_KW = re.compile(
    r"(运动.{0,5}(情绪|心情|焦虑|抑郁)|跑步.{0,5}(压力|心情)|"
    r"健身.{0,5}心理|瑜伽.{0,5}放松)"
)


def _detect_redline(user_msg: str) -> str | None:
    """Return crisis type if redline keywords matched."""
    if _REDLINE_KW.search(user_msg):
        return "self_harm"
    if _SEVERE_DEPRESSION_KW.search(user_msg):
        return "severe_depression"
    if _PANIC_KW.search(user_msg):
        return "panic_attack"
    return None


def _pick_tag_filter(user_msg: str) -> str | None:
    """Bias retrieval to the most relevant tag, if any."""
    if _SLEEP_KW.search(user_msg):
        return "sleep"
    if _ANXIETY_KW.search(user_msg):
        return "anxiety"
    if _DEPRESSION_KW.search(user_msg):
        return "depression"
    if _STRESS_KW.search(user_msg):
        return "stress"
    if _SOCIAL_KW.search(user_msg):
        return "social"
    return None


MENTAL_PROMPT = """你是 HealthCoachAgent 的心理健康教练（基于 APA/WHO 指南）。

任务：基于下面提供的 (a) 用户画像 (b) 知识库引用片段，对用户的问题给出
**温暖、支持性、可执行**的回答。

要求：
- 中文，自然友好，**不超过 6 句话**
- 至少包含一条具体技巧（呼吸法/正念/行为激活等）
- 在回答末尾用 (id1, id2) 形式标出引用到的 doc id（来自下面的 [refs]）
- 不诊断；不开处方；严重症状必须建议专业帮助
- 若 [refs] 中包含 redline 标签的引用，**必须**把危机干预建议放在第一句
- 若需要营养配合（Omega-3/益生菌/色氨酸等），最后追加一行：HANDOFF: nutrition（只允许 nutrition/fitness/mental/data）
- 若需要运动配合（有氧/瑜伽/跑步等），最后追加一行：HANDOFF: fitness（只允许 nutrition/fitness/mental/data）
- 严禁向 mental 自身 handoff

红线原则：
- 自伤/自杀意念 → 必须提供危机热线 + 建议告知可信赖的人 + 前往医院急诊
- 严重抑郁（2周以上功能受损）→ 建议精神科或心理咨询门诊
- 惊恐发作（首次）→ 建议急诊排除心脏急症，确诊后 CBT+药物联合
"""

async def mental_coach_node(state: AgentState) -> Command[Any]:
    user_id = state.get("user_id", "anon")
    user_msg = state.get("user_message", "") or ""

    # ---- 1. Crisis detection (redline) ----
    redline_type = _detect_redline(user_msg)
    if redline_type:
        log.warning("mental_redline_detected", type=redline_type, user_id=user_id)
        crisis_answer = _build_crisis_response(redline_type)
        coach_answer: CoachAnswer = {
            "coach": "mental",
            "text": crisis_answer,
            "citations": [],
            "metadata": {
                "provider": "crisis-response",
                "model": "rule-based",
                "redline": redline_type,
            },
        }
        return Command(
            update={
                "coach_answers": [coach_answer],
                "visited_coaches": ["mental"],
                "handoff_to": None,
            },
            goto="supervisor",
        )

    # ---- 2. User profile + memory context ----
    profile_block = "（暂无用户画像）"
    profile_dict: dict[str, Any] = {}
    memory_block = "（暂无记忆上下文）"
    try:
        from ...db import session_scope
        from ...db import repository as repo

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
        log.warning("mental_profile_load_failed", error=str(e))

    # ---- 3. RAG with optional tag filter ----
    rag = get_mental_retriever()
    tag_filter = _pick_tag_filter(user_msg)
    rag_query_parts = [user_msg]
    if profile_dict.get("goal"):
        rag_query_parts.append(profile_dict["goal"])
    rag_query = " ".join(rag_query_parts).strip() or "心理健康"
    
    # Exclude redline tags unless crisis detected
    exclude = ["redline"] if not redline_type else None
    
    hits = rag.search(rag_query, k=4, tag_filter=tag_filter, exclude_tags=exclude)
    # If a tag filter dropped everything, fall back to global top-k.
    if not hits:
        hits = rag.search(rag_query, k=4, exclude_tags=exclude)
    citations = format_citations(hits)
    refs_block = "\n".join(f"  - {c['id']}: {c['quote']}" for c in citations) or "（无引用）"

    # ---- 4. LLM ----
    user_payload = (
        f"[记忆上下文]\n{memory_block}\n\n"
        f"[用户画像]\n{profile_block}\n\n"
        f"[refs]\n{refs_block}\n\n"
        f"[用户问题]\n{user_msg or '（请基于以上给出心理健康建议）'}"
    )

    router = get_router()
    lf = get_langfuse()
    answer_text = ""
    provider, model = "", ""
    messages = [
        ChatMessage(role="system", content=MENTAL_PROMPT),
        ChatMessage(role="user", content=user_payload),
    ]
    try:
        if lf is not None:
            with lf.start_as_current_observation(
                name="mental_coach", as_type="generation"
            ) as gen:
                gen.update(input=[m.model_dump() for m in messages])
                resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=500)
                gen.update(
                    output=resp.content,
                    model=resp.model,
                    metadata={"provider": resp.provider, "user_id": user_id, "tag_filter": tag_filter},
                )
        else:
            resp = await router.chat("main_chat", messages, temperature=0.4, max_tokens=500)
        answer_text = resp.content
        provider, model = resp.provider, resp.model
    except ProviderError as e:
        log.warning("mental_llm_failed", error=str(e))
        answer_text = "[fallback] 无法连接模型；建议参考下方引用做基线决策。"

    # ---- 5. parse handoff ----
    handoff: str | None = None
    text = answer_text
    m = re.search(r"HANDOFF:\s*(\w+)", answer_text, flags=re.I)
    if m:
        cand = m.group(1).lower()
        valid = {"nutrition", "fitness", "mental", "data"}
        # Guard against self-handoff loops + invalid targets.
        if cand and cand != "mental" and cand in valid:
            handoff = cand
        elif cand and cand not in valid:
            log.warning("mental_handoff_invalid", raw=cand, mapped_to="fitness")
            handoff = "fitness"  # safe fallback
        text = re.sub(r"HANDOFF:\s*\w+\s*$", "", answer_text, flags=re.I).strip()
    elif _HANDOFF_NUTRITION_KW.search(user_msg):
        handoff = "nutrition"
    elif _HANDOFF_FITNESS_KW.search(user_msg):
        handoff = "fitness"

    coach_answer: CoachAnswer = {
        "coach": "mental",
        "text": text,
        "citations": citations,
        "metadata": {
            "provider": provider,
            "model": model,
            "rag_hits": len(citations),
            "tag_filter": tag_filter,
            "had_profile": bool(profile_dict),
        },
    }

    log.info(
        "mental_coach_done",
        rag_hits=len(citations), tag_filter=tag_filter, handoff=handoff,
    )

    return Command(
        update={
            "coach_answers": [coach_answer],
            "visited_coaches": ["mental"],
            "handoff_to": handoff,
        },
        goto="supervisor",
    )


def _build_crisis_response(crisis_type: str) -> str:
    """Build immediate crisis response (no LLM call)."""
    if crisis_type == "self_harm":
        return (
            "【危机干预】如果您有自伤或自杀意念，请立即拨打："
            "中国24小时心理援助热线 400-161-9995（北京心理危机干预热线）。"
            "同时，请尽快告知一位您信任的亲友或家人，并前往最近的医院急诊心理科。"
            "您的安全是第一优先级。请不要独自承受，帮助随时可用。"
            "\n\n（如果您正处于紧急危险中，请立即拨打 120 或前往急诊。）"
        )
    elif crisis_type == "severe_depression":
        return (
            "【严重抑郁预警】您描述的症状（持续2周以上功能受损）"
            "建议尽快前往三甲医院精神科或心理咨询门诊进行专业评估。"
            "同时，您可以拨打心理援助热线 400-161-9995 获得即时支持。"
            "这段时间很艰难，但专业帮助可以显著改善症状，请不要独自承受。"
        )
    elif crisis_type == "panic_attack":
        return (
            "【惊恐发作】如果您是首次出现心悸、胸闷、窒息感等症状，"
            "建议立即就医，先前往急诊排除心脏急症（如心梗、心律失常）。"
            "确诊惊恐障碍后，CBT（认知行为疗法）+ SSRI药物联合治疗效果最佳。"
            "发作时可尝试放松技巧：4-7-8 呼吸法（吸气4秒→屏息7秒→呼气8秒）缓解症状。"
            "建议尽快预约精神科或心理门诊进行专业评估。"
        )
    return "【危机干预】建议您立即联系专业心理健康资源。"


__all__ = ["mental_coach_node"]
