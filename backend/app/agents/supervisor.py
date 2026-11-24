"""Supervisor: routes user intent to a coach.

Strategy:
  1. Cheap heuristics first (fast path)
       - if image_path set → nutrition
       - if obvious运动 keywords → fitness
  2. LLM tie-breaker for ambiguous cases (uses cheap router model)

Loop guard: visit each coach at most once unless explicit handoff.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langgraph.types import Command

from ..core.langfuse_client import get_langfuse
from ..core.logging import get_logger
from ..llm import ChatMessage, get_router
from ..llm.types import ProviderError
from .state import AgentState

log = get_logger(__name__)


# ---------- heuristics ----------

_FITNESS_KW = re.compile(
    r"(运动|训练|跑步|健身|举铁|举哑铃|力量|有氧|hiit|跑了|步数|"
    r"心率|拉伸|瑜伽|游泳|骑车|骑行|爬山|拉伤|肌肉|酸痛)",
    flags=re.I,
)

_DATA_KW = re.compile(
    r"(本周|这周|本月|最近.{0,3}天|趋势|平均|对比|统计|多少天|"
    r"几餐|总共|累计|汇总|报告|达标率|比例|分布|相关性|最大|"
    r"查询|记录|摄入|消耗|睡眠|体重|体脂|HRV|心率|"
    r"运动类型|类型分布|数据|分析|健康报告|评分|"
    r"目标|调整|设置|修改|更新|档案|个人资料)"
)

_MENTAL_KW = re.compile(
    r"(焦虑|抑郁|压力大|睡不着|失眠|情绪低落|烦躁|紧张|恐慌|"
    r"心情|情绪|心理|精神|放松|冥想|正念|社交|孤独| burnout|"
    r"工作压力大|想不开|没动力|提不起劲)"
)

_NUTRITION_KW = re.compile(
    r"(吃|餐|饭|营养|热量|蛋白|碳水|脂肪|纤维|减脂|增肌|食物|"
    r"早餐|午餐|晚餐|零食|加餐|喝)"
)


def _heuristic_route(state: AgentState) -> str | None:
    if state.get("image_path"):
        return "nutrition"
    msg = state.get("user_message", "")
    if not msg:
        return None
    n_fit = len(_FITNESS_KW.findall(msg))
    n_data = len(_DATA_KW.findall(msg))
    n_nut = len(_NUTRITION_KW.findall(msg))
    n_mental = len(_MENTAL_KW.findall(msg))
    # only act on a strong unambiguous lead
    candidates = [
        (n_fit, "fitness"),
        (n_data, "data"),
        (n_nut, "nutrition"),
        (n_mental, "mental"),
    ]
    candidates.sort(reverse=True)
    if candidates[0][0] == 0:
        return None  # nothing matched
    if candidates[0][0] >= candidates[1][0] + 1:
        # winner has at least 1 more hit than runner-up
        return candidates[0][1]
    return None


# ---------- LLM tie-breaker ----------

ROUTER_PROMPT = """你是 HealthCoachAgent 的调度员。
根据用户消息，从 ['nutrition', 'fitness', 'mental', 'data', 'end'] 中**只输出一个**：

- nutrition：饮食、营养、热量、餐食、过敏、增肌减脂
- fitness：运动、训练、跑步、举铁、心率、拉伸、伤病恢复
- mental：情绪、压力、焦虑、抑郁、失眠、正念、社交、心理
- data：用户问"最近怎么样/趋势/对比/汇总"等需要查历史数据的问题
- end：纯闲聊或者已经回答完毕、无需任何专家

只输出一个英文小写单词，不要解释，不要 markdown。

示例：
用户: 你好
答: end
用户: 这两周训练量比上两周怎么样
答: data
用户: 跑完一小时该补什么糖？
答: fitness
用户: 我目标减脂，每天 1700 kcal 怎么分配蛋白
答: nutrition
用户: 训练时胸口很闷有点头晕，正常吗
答: fitness
用户: 这周饮食和睡眠的趋势都给我看下
答: data
用户: 最近压力很大，晚上睡不着怎么办
答: mental
用户: 总是很焦虑，有什么办法放松吗
答: mental
用户: 感觉很孤独，不想社交
答: mental"""


async def _llm_route(state: AgentState) -> str:
    """Cheap LLM call to break heuristic ties.

    Robust parsing:
      1. strip quotes/markdown
      2. take first whitespace-separated token, lowercase
      3. if not in {nutrition, fitness, mental, data, end}, scan the whole reply
         for the first valid keyword (handles "答: nutrition" / "nutrition.")
      4. otherwise default to 'end'
    """
    msg = state.get("user_message", "")
    router = get_router()
    valid = {"nutrition", "fitness", "mental", "data", "end"}
    try:
        resp = await router.chat(
            "router",
            [
                ChatMessage(role="system", content=ROUTER_PROMPT),
                ChatMessage(role="user", content=msg or "你好"),
            ],
            temperature=0.0,
            max_tokens=8,
        )
        raw = (resp.content or "").strip().strip('"').strip("'").lower()
        if raw:
            head = re.split(r"[\s,.:;]+", raw, maxsplit=1)[0]
            if head in valid:
                return head
            # fallback: scan
            for w in valid:
                if w in raw:
                    return w
    except ProviderError as e:
        log.warning("router_llm_failed", error=str(e))
    return "end"


# ---------- supervisor node ----------


async def supervisor_node(state: AgentState) -> Command[Any]:
    """Decide the next coach (or end). Updates state.next_coach."""
    visited = set(state.get("visited_coaches") or set())
    explicit = state.get("handoff_to")

    # 1) explicit handoff from a coach takes precedence
    if explicit and explicit not in visited:
        # Validate handoff target
        valid_coaches = {"nutrition", "fitness", "mental", "data"}
        if explicit not in valid_coaches:
            log.warning("supervisor_invalid_handoff", to=explicit, falling_back_to="finalize")
            return Command(update={"next_coach": "end"}, goto="finalize")
        log.info("supervisor_explicit_handoff", to=explicit)
        return Command(
            update={"next_coach": explicit, "handoff_to": None},
            goto=explicit,
        )

    # 2) if every coach the message could plausibly need has been visited, end
    if len(visited) >= 2:  # cap collaboration depth (W3 D1: 1 main + 1 handoff)
        log.info("supervisor_loop_guard_end", visited=sorted(visited))
        return Command(update={"next_coach": "end"}, goto="finalize")

    # 3) heuristic
    decision = _heuristic_route(state)
    method = "heuristic"
    if decision is None:
        decision = await _llm_route(state)
        method = "llm"
    
    # 无论 heuristic 还是 llm，都要检查 visited
    if decision in visited:
        # avoid revisit; pick first non-visited or end
        for alt in ("nutrition", "fitness", "mental", "data"):
            if alt not in visited:
                decision = alt
                method = "alt"
                break
        else:
            decision = "end"

    log.info(
        "supervisor_decided",
        next_coach=decision, method=method,
        visited=sorted(visited),
    )

    # Optional: report decision to Langfuse for observability
    lf = get_langfuse()
    if lf is not None:
        with lf.start_as_current_observation(name="supervisor_route", as_type="span") as span:
            span.update(
                input={"user_message": state.get("user_message"),
                       "image": bool(state.get("image_path"))},
                output={"next_coach": decision, "method": method},
            )

    if decision == "end":
        return Command(update={"next_coach": "end"}, goto="finalize")
    return Command(update={"next_coach": decision}, goto=decision)


# ---------- finalize node ----------


FINALIZE_PRIMARY_PROMPT = """你是 HealthCoachAgent 的最终回答合成器。

下面给出多位 coach 的草稿。请按"主答案 + 一句补充"模式合并：
- 第一段：完整保留【主 coach】的回答（保留具体数字与引用 id）
- 末尾追加一句：【补充 coach】的最关键一点（≤30字），用"另外，..."开头
- 输出**纯文本**，不要 markdown 标题、列表、加粗
- 不重复内容；若两段冲突，以主 coach 为准
"""

FINALIZE_SAFETY_PROMPT = """你是 HealthCoachAgent 的最终回答合成器。

下方草稿中至少有一条**安全红线**引用（safety tag），请按"红线优先"合并：
- **第一句**：明确告知用户该红线建议（停止训练 / 立即就医 等），引用对应 doc id
- 第二段：把其他 coach 的具体行动建议浓缩成 2-3 句
- 输出纯文本，不用 markdown
- 严禁淡化或绕过安全建议
"""


def _has_safety_citation(answers: list[dict]) -> bool:
    """A 'red-line' citation = tag 'redline' OR metadata.redline exists.

    Note: tag 'safety' alone is too broad (training-safety advice like
    HIIT progression also uses it). Only 'redline' triggers safety_first
    finalize mode, which forces the merge prompt to put the warning
    in the very first sentence.
    """
    for a in answers:
        # Check citations for redline tag
        for c in a.get("citations", []) or []:
            if "redline" in (c.get("tags") or []):
                return True
        # Also check metadata for redline field (set by mental_coach crisis detection)
        if a.get("metadata", {}).get("redline"):
            return True
    return False


def _dedup_citations(answers: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for a in answers:
        for c in a.get("citations", []) or []:
            cid = c.get("id", "")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(c)
    return out


async def finalize_node(state: AgentState) -> dict:
    """Combine coach answers into the final user-facing text.

    Three modes:
      - passthrough  : single coach, return as-is
      - safety_first : any answer cites a safety-tagged doc → red-line first
      - primary_addon: 2 coaches, first visited = primary, second = addon
    """
    answers = state.get("coach_answers") or []
    visited = state.get("visited_coaches") or []
    if not answers:
        return {
            "final_answer": "（暂无可回答内容）",
            "final_citations": [],
            "final_provider": "none",
            "final_model": "none",
            "final_mode": "empty",
        }

    citations = _dedup_citations(answers)

    # ---- mode 1: passthrough ----
    if len(answers) == 1:
        a = answers[0]
        return {
            "final_answer": a.get("text", ""),
            "final_citations": a.get("citations", []),
            "final_provider": a.get("metadata", {}).get("provider", ""),
            "final_model": a.get("metadata", {}).get("model", ""),
            "final_mode": "passthrough",
        }

    # ---- mode 2: safety_first ----
    safety = _has_safety_citation(answers)

    # ---- mode 3 setup ----
    # Map coach name → answer for explicit ordering
    by_coach = {a.get("coach"): a for a in answers}
    primary_name = next((c for c in visited if c in by_coach), answers[0].get("coach"))
    addon_name = next(
        (c for c in visited if c in by_coach and c != primary_name),
        next((a.get("coach") for a in answers if a.get("coach") != primary_name), None),
    )
    primary = by_coach.get(primary_name) or answers[0]
    addon = by_coach.get(addon_name) if addon_name else None

    if safety:
        prompt = FINALIZE_SAFETY_PROMPT
        mode = "safety_first"
        body = "\n\n".join(
            f"【{a.get('coach','?')}教练】\n{a.get('text','')}" for a in answers
        )
    else:
        prompt = FINALIZE_PRIMARY_PROMPT
        mode = "primary_addon"
        body = (
            f"【主 coach: {primary_name}】\n{primary.get('text','')}\n\n"
            f"【补充 coach: {addon_name}】\n{(addon or {}).get('text','') if addon else '（无）'}"
        )

    router = get_router()
    try:
        resp = await router.chat(
            "main_chat",
            [
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=body),
            ],
            temperature=0.3,
            max_tokens=500,
        )
        merged_text = resp.content
        provider, model = resp.provider, resp.model
    except ProviderError as e:
        log.warning("finalize_merge_failed", error=str(e), mode=mode)
        # Deterministic fallback: just concat with a clear separator
        merged_text = body
        provider, model = "fallback-concat", ""

    log.info("finalize_done", mode=mode, n_answers=len(answers),
             n_citations=len(citations), provider=provider)

    return {
        "final_answer": merged_text,
        "final_citations": citations,
        "final_provider": provider,
        "final_model": model,
        "final_mode": mode,
    }


__all__ = ["supervisor_node", "finalize_node"]
