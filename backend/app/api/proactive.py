"""主动型 Agent API 路由。

提供触发器管理、HITL 确认、通知配置等端点。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from ...app.proactive import (
    HITLStatus,
    TriggerConfig,
    TriggerKind,
    TriggerStatus,
    get_job_executor,
    get_notification_service,
    get_trigger_engine,
)
from ...app.proactive.jobs import daily_report_job, protein_low_alert_job

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


# ========== 请求/响应模型 ==========

class CreateTriggerRequest(BaseModel):
    """创建触发器请求。"""
    
    user_id: str = Field(..., description="用户ID")
    kind: TriggerKind = Field(..., description="触发器类型")
    name: str = Field(default="", description="触发器名称")
    description: str = Field(default="", description="触发器描述")
    
    # 定时触发器字段
    cron_expr: Optional[str] = Field(default=None, description="Cron表达式")
    interval_seconds: Optional[int] = Field(default=None, description="间隔时间（秒）")
    
    # 阈值触发器字段
    metric: Optional[str] = Field(default=None, description="监控指标")
    threshold_value: Optional[float] = Field(default=None, description="阈值")
    threshold_direction: Optional[str] = Field(default=None, description="阈值方向")
    
    # 事件触发器字段
    event_type: Optional[str] = Field(default=None, description="事件类型")
    
    # HITL配置
    hitl_enabled: bool = Field(default=True, description="是否启用HITL")
    
    # 元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class TriggerResponse(BaseModel):
    """触发器响应。"""
    
    trigger_id: str
    user_id: str
    kind: str
    name: str
    description: str
    enabled: bool
    hitl_enabled: bool
    created_at: datetime
    metadata: Dict[str, Any]


class HITLApproveRequest(BaseModel):
    """HITL 批准请求。"""
    
    trigger_id: str = Field(..., description="触发器ID")
    user_id: str = Field(..., description="用户ID")
    approved: bool = Field(..., description="是否批准")
    comment: Optional[str] = Field(default=None, description="用户评论")


class NotificationRequest(BaseModel):
    """发送通知请求。"""
    
    user_id: str = Field(..., description="用户ID")
    title: str = Field(..., description="通知标题")
    message: str = Field(..., description="通知内容")
    priority: str = Field(default="normal", description="优先级")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")


# ========== 触发器管理端点 ==========

@router.get("/triggers", response_model=List[Dict[str, Any]])
async def list_triggers(
    user_id: str = Query(..., description="用户ID"),
    kind: Optional[TriggerKind] = Query(default=None, description="过滤器：触发器类型"),
    enabled_only: bool = Query(default=False, description="仅返回启用的触发器"),
):
    """列出用户的所有触发器。"""
    engine = get_trigger_engine()
    triggers = []
    
    for trigger_id, config in engine._triggers.items():
        if config.user_id != user_id:
            continue
        if kind and config.kind != kind:
            continue
        if enabled_only and not config.enabled:
            continue
        
        triggers.append({
            "trigger_id": trigger_id,
            "user_id": config.user_id,
            "kind": config.kind.value,
            "name": config.name,
            "description": config.description,
            "enabled": config.enabled,
            "hitl_enabled": config.hitl_enabled,
            "created_at": config.created_at,
            "metadata": config.metadata,
        })
    
    return triggers


@router.post("/triggers", response_model=Dict[str, Any])
async def create_trigger(request: CreateTriggerRequest):
    """创建并注册一个新的触发器。"""
    import uuid
    
    trigger_id = f"{request.kind.value}_{uuid.uuid4().hex[:8]}"
    
    config = TriggerConfig(
        trigger_id=trigger_id,
        user_id=request.user_id,
        kind=request.kind,
        name=request.name,
        description=request.description,
        cron_expr=request.cron_expr,
        interval_seconds=request.interval_seconds,
        metric=request.metric,
        threshold_value=request.threshold_value,
        threshold_direction=request.threshold_direction,
        event_type=request.event_type,
        hitl_enabled=request.hitl_enabled,
        metadata=request.metadata,
    )
    
    # 验证配置
    try:
        config.validate_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 注册到触发器引擎
    engine = get_trigger_engine()
    engine.register(config)
    
    # 如果是定时触发器，也注册到JobExecutor
    if config.kind == TriggerKind.TIMER:
        from ...app.proactive.jobs import get_job_executor
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        
        # 这里需要有一个全局的scheduler实例
        # 暂时跳过，在实际集成时需要完善
        logger.info(f"Timer trigger created: {trigger_id}")
    
    return {
        "trigger_id": trigger_id,
        "message": "Trigger created successfully",
    }


@router.delete("/triggers/{trigger_id}")
async def delete_trigger(trigger_id: str, user_id: str = Query(..., description="用户ID")):
    """删除一个触发器。"""
    engine = get_trigger_engine()
    config = engine._triggers.get(trigger_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Trigger not found")
    
    if config.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    engine.unregister(trigger_id)
    
    return {"message": "Trigger deleted successfully"}


@router.put("/triggers/{trigger_id}/toggle")
async def toggle_trigger(
    trigger_id: str,
    user_id: str = Query(..., description="用户ID"),
    enabled: bool = Query(..., description="启用/禁用"),
):
    """启用或禁用触发器。"""
    engine = get_trigger_engine()
    config = engine._triggers.get(trigger_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Trigger not found")
    
    if config.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    config.enabled = enabled
    
    return {
        "trigger_id": trigger_id,
        "enabled": enabled,
        "message": f"Trigger {'enabled' if enabled else 'disabled'} successfully",
    }


# ========== HITL 端点 ==========

@router.get("/hitl/pending")
async def get_pending_hitl(user_id: str = Query(..., description="用户ID")):
    """获取待用户确认的 HITL 触发器。"""
    engine = get_trigger_engine()
    pending = engine.get_pending_hitl(user_id)
    
    return [
        {
            "trigger_id": r.trigger_id,
            "user_id": r.user_id,
            "triggered_at": r.triggered_at,
            "context": r.context.dict(),
            "hitl_status": r.hitl_status,
        }
        for r in pending
    ]


@router.post("/hitl/approve")
async def approve_hitl(request: HITLApproveRequest):
    """批准或拒绝 HITL 触发器。"""
    engine = get_trigger_engine()
    
    if request.approved:
        success = await engine.approve_hitl(request.trigger_id, request.user_id)
    else:
        success = await engine.reject_hitl(request.trigger_id, request.user_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="HITL request not found")
    
    return {
        "trigger_id": request.trigger_id,
        "approved": request.approved,
        "message": f"HITL {'approved' if request.approved else 'rejected'} successfully",
    }


# ========== 通知端点 ==========

@router.post("/notify")
async def send_notification(request: NotificationRequest):
    """发送通知。"""
    service = get_notification_service()
    
    from ...app.proactive.notifications import NotificationPriority
    
    try:
        priority = NotificationPriority(request.priority)
    except ValueError:
        priority = NotificationPriority.NORMAL
    
    results = await service.send_notification(
        user_id=request.user_id,
        title=request.title,
        message=request.message,
        priority=priority,
        metadata=request.metadata,
    )
    
    return {
        "message": "Notification sent",
        "results": results,
    }


# ========== 预定义触发器快捷创建 ==========

@router.post("/triggers/daily-report")
async def create_daily_report_trigger(
    user_id: str = Query(..., description="用户ID"),
    hour: int = Query(default=8, ge=0, le=23, description="每日报告时间（小时）"),
    minute: int = Query(default=0, ge=0, le=59, description="每日报告时间（分钟）"),
    hitl_enabled: bool = Query(default=False, description="是否启用HITL"),
):
    """创建每日健康报告触发器。"""
    import uuid
    
    trigger_id = f"daily_report_{uuid.uuid4().hex[:8]}"
    cron_expr = f"{minute} {hour} * * *"
    
    config = TriggerConfig(
        trigger_id=trigger_id,
        user_id=user_id,
        kind=TriggerKind.TIMER,
        name="每日健康报告",
        description=f"每天 {hour:02d}:{minute:02d} 生成健康报告",
        cron_expr=cron_expr,
        hitl_enabled=hitl_enabled,
        metadata={"job_type": "daily_report"},
    )
    
    engine = get_trigger_engine()
    engine.register(config)
    
    return {
        "trigger_id": trigger_id,
        "cron_expr": cron_expr,
        "message": "Daily report trigger created successfully",
    }


@router.post("/triggers/protein-alert")
async def create_protein_alert_trigger(
    user_id: str = Query(..., description="用户ID"),
    threshold: float = Query(default=50.0, description="蛋白质摄入阈值（克/天）"),
    lookback_days: int = Query(default=7, description="统计天数"),
    hitl_enabled: bool = Query(default=True, description="是否启用HITL"),
):
    """创建蛋白质摄入不足提醒触发器。"""
    import uuid
    
    trigger_id = f"protein_alert_{uuid.uuid4().hex[:8]}"
    
    config = TriggerConfig(
        trigger_id=trigger_id,
        user_id=user_id,
        kind=TriggerKind.THRESHOLD,
        name="蛋白质摄入不足提醒",
        description=f"最近 {lookback_days} 天平均蛋白质摄入低于 {threshold}g/天时提醒",
        metric="protein_intake",
        threshold_value=threshold,
        threshold_direction="below",
        hitl_enabled=hitl_enabled,
        metadata={
            "lookback_days": lookback_days,
            "job_type": "protein_alert",
        },
    )
    
    engine = get_trigger_engine()
    engine.register(config)
    
    return {
        "trigger_id": trigger_id,
        "threshold": threshold,
        "message": "Protein alert trigger created successfully",
    }


# ========== 手动触发端点 ==========

@router.post("/triggers/{trigger_id}/run")
async def run_trigger_now(
    trigger_id: str,
    user_id: str = Query(..., description="用户ID"),
):
    """立即运行一个触发器（用于测试）。"""
    engine = get_trigger_engine()
    config = engine._triggers.get(trigger_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Trigger not found")
    
    if config.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 手动触发
    from ...app.proactive.jobs import get_job_executor
    
    executor = get_job_executor()
    result = await executor.run_job_now(trigger_id, user_id)
    
    if not result:
        raise HTTPException(status_code=500, detail="Job execution failed")
    
    return {
        "trigger_id": trigger_id,
        "result": result.dict(),
        "message": "Trigger executed successfully",
    }


@router.get("/check")
async def check_triggers(user_id: str = Query(..., description="用户ID")):
    """手动检查用户的触发器（用于测试）。"""
    engine = get_trigger_engine()
    contexts = await engine.check_all(user_id)
    
    return {
        "user_id": user_id,
        "triggered_count": len(contexts),
        "contexts": [ctx.dict() for ctx in contexts],
    }
