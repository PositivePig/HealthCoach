"""Built-in scheduled job kinds.

Importing this module is enough to register the kinds in scheduler.core's
_JOB_KINDS registry (decorator side-effect).

Each job:
  * receives (user_id, payload)
  * does its work (DB read, optional LLM call)
  * usually writes a Notification with status='draft' for HITL approval
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.langfuse_client import get_langfuse
from ..core.logging import get_logger
from ..db import session_scope
from ..db.models import Notification
from ..db import repository as repo
from ..llm import ChatMessage, get_router
from .core import register_job_kind

log = get_logger(__name__)


# ---------- internal helpers ----------


async def _create_draft_notification(
    user_id: str, *, kind: str, title: str, body: str, metadata: dict[str, Any]
) -> int:
    """Persist a Notification draft. Returns notification id."""
    async with session_scope() as session:
        n = Notification(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            metadata_json=metadata,
            status="draft",
        )
        session.add(n)
        await session.flush()
        return n.id


# ---------- daily_report ----------

DAILY_REPORT_PROMPT = """你是 HealthCoachAgent 的数据分析师。
基于下面的近 N 天营养摄入数据，写一份简短的"每日健康日报草稿"，给到用户审批。
风格：友好、简洁、最多 5 句话；含一条具体的数据观察 + 一条明天的小建议。
不要编造数据。如果数据为空，明确指出"今天没有记录餐次，建议明天开始尝试拍照记录"。
直接输出文本，不要 markdown 代码块。
"""


@register_job_kind("daily_report")
async def daily_report(user_id: str, payload: dict[str, Any]) -> None:
    """Aggregate the user's recent nutrition + draft a friendly report message."""
    days = int(payload.get("window_days", 1))
    log.info("daily_report_running", user_id=user_id, days=days)

    async with session_scope() as session:
        agg = await repo.aggregate_nutrition(session, user_id, days=days)
        recent_meals = await repo.query_meals(session, user_id, days=days, limit=10)

    meal_names = []
    for m in recent_meals:
        items = m.dishes or []
        meal_names.extend(i.get("name", "") for i in items)

    facts = (
        f"窗口：近 {days} 天\n"
        f"餐次数：{agg['meal_count']}\n"
        f"总热量：{agg['total_kcal']} kcal\n"
        f"总蛋白质：{agg['total_protein_g']} g\n"
        f"总碳水：{agg['total_carbs_g']} g\n"
        f"总脂肪：{agg['total_fat_g']} g\n"
        f"日均热量：{agg['avg_kcal_per_day']} kcal\n"
        f"涉及食材：{', '.join(meal_names) if meal_names else '（无）'}\n"
    )

    router = get_router()
    lf = get_langfuse()
    messages = [
        ChatMessage(role="system", content=DAILY_REPORT_PROMPT),
        ChatMessage(role="user", content=facts),
    ]

    # If no providers configured (e.g. tests w/o keys), short-circuit to a
    # deterministic fallback text so the job still produces a draft.
    available = [p for p in router.list_providers("main_chat") if p.available]
    if not available:
        body = (
            f"[模板版] 今日日报：餐次 {agg['meal_count']} 条，"
            f"总热量 {agg['total_kcal']} kcal，"
            f"总蛋白 {agg['total_protein_g']} g。"
            f"明天目标：均衡补充蛋白与蔬菜。"
        )
    else:
        if lf is not None:
            with lf.start_as_current_observation(
                name="job_daily_report", as_type="generation"
            ) as gen:
                gen.update(input=[m.model_dump() for m in messages])
                resp = await router.chat("main_chat", messages, temperature=0.4)
                gen.update(
                    output=resp.content,
                    model=resp.model,
                    metadata={"provider": resp.provider, "usage": resp.usage,
                              "user_id": user_id},
                )
        else:
            resp = await router.chat("main_chat", messages, temperature=0.4)
        body = resp.content

    title = (
        f"📊 健康日报草稿 ({datetime.now(tz=timezone.utc).date().isoformat()}, "
        f"近 {days} 天)"
    )
    nid = await _create_draft_notification(
        user_id,
        kind="daily_report",
        title=title,
        body=body,
        metadata={"window_days": days, "stats": agg},
    )
    log.info("daily_report_drafted", user_id=user_id, notification_id=nid)


# ---------- protein_low_alert (threshold-style example) ----------


@register_job_kind("protein_low_alert")
async def protein_low_alert(user_id: str, payload: dict[str, Any]) -> None:
    """Check if avg daily protein < target_g over last `days` days; if so, draft an alert."""
    days = int(payload.get("days", 3))
    target_g = float(payload.get("target_protein_per_day", 60.0))

    async with session_scope() as session:
        agg = await repo.aggregate_nutrition(session, user_id, days=days)

    avg_protein = agg["avg_protein_per_day"]
    if avg_protein >= target_g:
        log.info(
            "protein_alert_skipped",
            user_id=user_id, avg=avg_protein, target=target_g,
        )
        return

    body = (
        f"⚠️ 蛋白质摄入提醒\n\n"
        f"近 {days} 天日均蛋白质摄入仅 {avg_protein} g，"
        f"低于目标 {target_g} g。\n"
        f"建议明天加一份高蛋白食物（鸡蛋 / 豆腐 / 鸡胸 / 希腊酸奶）。"
    )
    nid = await _create_draft_notification(
        user_id,
        kind="protein_low_alert",
        title="蛋白质摄入偏低",
        body=body,
        metadata={"avg_protein": avg_protein, "target_g": target_g, "days": days},
    )
    log.info("protein_alert_drafted", user_id=user_id, notification_id=nid)


# ---------- dispatch_pending (W2 D4) ----------


@register_job_kind("dispatch_pending")
async def dispatch_pending_job(user_id: str, payload: dict[str, Any]) -> None:
    """Pick all approved notifications and send via their configured channels.

    user_id: if not "*", restrict to that user; "*" means all users.
    payload: {"limit": int = 50}
    """
    from ..notify import dispatch_pending  # local import to avoid circular

    limit = int(payload.get("limit", 50))
    target_uid = None if user_id == "*" else user_id
    results = await dispatch_pending(user_id=target_uid, limit=limit)
    sent = sum(1 for r in results if r.get("status") == "sent")
    failed = sum(1 for r in results if r.get("status") == "failed")
    retrying = sum(1 for r in results if r.get("status") == "approved")
    log.info(
        "dispatch_pending_done",
        total=len(results), sent=sent, failed=failed, retrying=retrying,
    )
