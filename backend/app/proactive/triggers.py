"""主动型 Agent 触发器系统。

实现三类触发器：
1. 定时触发器（TimerTrigger）：按cron/interval执行
2. 阈值触发器（ThresholdTrigger）：数据超过阈值时触发
3. 事件触发器（EventTrigger）：特定事件发生时触发

每个触发器都可以：
- 检查是否应该触发
- 生成触发上下文（供Coach节点使用）
- 通过HITL（Human-In-The-Loop）机制等待用户确认
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import text

from ..db.models import EpisodicEvent, ProceduralPreference
from ..db.engine import session_scope as async_session
from .types import (
    TriggerConfig,
    TriggerContext,
    TriggerKind,
    TriggerResult,
)


class TriggerEngine:
    """主动型触发器引擎。
    
    负责：
    1. 注册和管理触发器
    2. 定期检查触发器条件
    3. 生成触发上下文
    4. 与HITL机制集成
    """
    
    def __init__(self):
        self._triggers: Dict[str, TriggerConfig] = {}
        self._results: List[TriggerResult] = []
        
    def register(self, config: TriggerConfig) -> None:
        """注册一个触发器。"""
        if config.trigger_id in self._triggers:
            logger.warning(f"Trigger {config.trigger_id} already registered, overwriting")
        self._triggers[config.trigger_id] = config
        logger.info(
            "trigger_registered",
            trigger_id=config.trigger_id,
            kind=config.kind if isinstance(config.kind, str) else config.kind.value,
            user_id=config.user_id,
        )
    
    def unregister(self, trigger_id: str) -> None:
        """注销一个触发器。"""
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            logger.info("trigger_unregistered", trigger_id=trigger_id)
    
    async def check_all(self, user_id: str) -> List[TriggerContext]:
        """检查用户的所有触发器，返回需要触发的上下文列表。"""
        contexts = []
        now = datetime.now(timezone.utc)
        
        for trigger_id, config in self._triggers.items():
            if config.user_id != user_id:
                continue
            
            if not config.enabled:
                continue
            
            # 检查是否应该触发
            should_trigger, metadata = await self._check_trigger(config)
            
            if should_trigger:
                # 生成触发上下文
                ctx = await self._build_context(config, metadata)
                contexts.append(ctx)
                
                # 记录触发结果
                result = TriggerResult(
                    trigger_id=trigger_id,
                    user_id=user_id,
                    triggered_at=now,
                    context=ctx,
                    hitl_status="pending" if config.hitl_enabled else "bypassed",
                )
                self._results.append(result)
                
                # 更新last_run时间
                config.metadata["last_run"] = now.isoformat()
                
                logger.info(
                    "trigger_fired",
                    trigger_id=trigger_id,
                    kind=config.kind if isinstance(config.kind, str) else config.kind.value,
                    hitl=config.hitl_enabled,
                )
        
        return contexts
    
    async def _check_trigger(
        self, config: TriggerConfig
    ) -> Tuple[bool, Dict[str, Any]]:
        """检查单个触发器是否应该触发。返回 (是否触发, 元数据)。"""
        
        # 兼容 use_enum_values=True 的情况
        kind_value = config.kind if isinstance(config.kind, str) else config.kind.value
        
        if kind_value == TriggerKind.TIMER.value:
            return await self._check_timer(config)
        elif kind_value == TriggerKind.THRESHOLD.value:
            return await self._check_threshold(config)
        elif kind_value == TriggerKind.EVENT.value:
            return await self._check_event(config)
        else:
            logger.error(f"Unknown trigger kind: {config.kind}")
            return False, {}
    
    async def _check_timer(self, config: TriggerConfig) -> Tuple[bool, Dict[str, Any]]:
        """检查定时触发器。"""
        now = datetime.now(timezone.utc)
        
        # 检查cron表达式或interval
        if config.cron_expr:
            # 使用APScheduler的CronTrigger解析cron表达式
            try:
                trigger = CronTrigger.from_crontab(config.cron_expr)
                
                # 获取上次触发时间
                last_run_str = config.metadata.get("last_run")
                
                if last_run_str is None:
                    # 第一次运行，检查是否应该立即触发
                    # 获取下次触发时间
                    next_fire_time = trigger.get_next_fire_time(None, now)
                    if next_fire_time and next_fire_time <= now:
                        return True, {"first_run": True, "next_fire_time": next_fire_time.isoformat()}
                else:
                    # 检查上次触发后是否有新的触发时间
                    last_run_dt = datetime.fromisoformat(last_run_str).replace(tzinfo=timezone.utc)
                    next_fire_time = trigger.get_next_fire_time(None, last_run_dt)
                    
                    if next_fire_time and next_fire_time <= now:
                        return True, {
                            "last_run": last_run_str,
                            "next_fire_time": next_fire_time.isoformat(),
                        }
                
            except Exception as e:
                logger.error(f"Cron expression parse error: {e}")
                return False, {}
        
        elif config.interval_seconds:
            # 检查距离上次触发的时间
            last_run_str = config.metadata.get("last_run")
            if last_run_str is None:
                return True, {"first_run": True}
            
            last_run_dt = datetime.fromisoformat(last_run_str).replace(tzinfo=timezone.utc)
            elapsed = (now - last_run_dt).total_seconds()
            
            if elapsed >= config.interval_seconds:
                return True, {"elapsed_seconds": elapsed}
        
        return False, {}
    
    async def _check_threshold(
        self, config: TriggerConfig
    ) -> Tuple[bool, Dict[str, Any]]:
        """检查阈值触发器。"""
        async with async_session() as session:
            # 查询最近N天的数据
            days = config.metadata.get("lookback_days", 7)
            metric = config.metric
            
            # 获取用户数据
            if metric == "protein_intake":
                # 查询最近N天的蛋白质摄入
                query = await session.execute(
                    text("""
                    SELECT AVG(total_protein_g) as avg_protein
                    FROM meals
                    WHERE user_id = :user_id
                    AND ts >= :start_date
                    """),
                    {
                        "user_id": config.user_id,
                        "start_date": datetime.now(timezone.utc) - timedelta(days=days),
                    },
                )
                row = query.first()
                
                if row and row.avg_protein is not None:
                    avg_protein = float(row.avg_protein)
                    threshold = config.threshold_value
                    
                    # 检查是否低于阈值
                    if config.threshold_direction == "below" and avg_protein < threshold:
                        return True, {
                            "avg_protein": avg_protein,
                            "threshold": threshold,
                            "days": days,
                        }
                    elif config.threshold_direction == "above" and avg_protein > threshold:
                        return True, {
                            "avg_protein": avg_protein,
                            "threshold": threshold,
                            "days": days,
                        }
        
        return False, {}
    
    async def _check_event(self, config: TriggerConfig) -> Tuple[bool, Dict[str, Any]]:
        """检查事件触发器。"""
        # 监听特定事件类型
        event_type = config.metadata.get("event_type")
        
        if event_type:
            # 查询最近是否发生了该事件
            async with async_session() as session:
                query = await session.execute(
                    text("""
                    SELECT COUNT(*) as cnt
                    FROM episodic_events
                    WHERE user_id = :user_id
                    AND event_type = :event_type
                    AND ts >= :start_date
                    """),
                    {
                        "user_id": config.user_id,
                        "event_type": event_type,
                        "start_date": datetime.now(timezone.utc) - timedelta(hours=1),
                    },
                )
                row = query.first()
                
                if row and row.cnt > 0:
                    return True, {"event_count": row.cnt}
        
        return False, {}
    
    async def _build_context(
        self, config: TriggerConfig, metadata: Dict[str, Any]
    ) -> TriggerContext:
        """构建触发上下文。"""
        return TriggerContext(
            trigger_id=config.trigger_id,
            user_id=config.user_id,
            kind=config.kind,
            triggered_at=datetime.now(timezone.utc),
            metadata=metadata,
            hitl_enabled=config.hitl_enabled,
        )
    
    def get_pending_hitl(self, user_id: str) -> List[TriggerResult]:
        """获取待用户确认的HITL触发器。"""
        return [
            r for r in self._results
            if r.user_id == user_id and r.hitl_status == "pending"
        ]
    
    async def approve_hitl(self, trigger_id: str, user_id: str) -> bool:
        """用户批准HITL触发器。"""
        for result in self._results:
            if result.trigger_id == trigger_id and result.user_id == user_id:
                if result.hitl_status == "pending":
                    result.hitl_status = "approved"
                    logger.info("hitl_approved", trigger_id=trigger_id)
                    return True
        
        logger.warning("hitl_not_found", trigger_id=trigger_id, user_id=user_id)
        return False
    
    async def reject_hitl(self, trigger_id: str, user_id: str) -> bool:
        """用户拒绝HITL触发器。"""
        for result in self._results:
            if result.trigger_id == trigger_id and result.user_id == user_id:
                if result.hitl_status == "pending":
                    result.hitl_status = "rejected"
                    logger.info("hitl_rejected", trigger_id=trigger_id)
                    return True
        
        logger.warning("hitl_not_found", trigger_id=trigger_id, user_id=user_id)
        return False


# 全局触发器引擎实例
_trigger_engine: Optional[TriggerEngine] = None


def get_trigger_engine() -> TriggerEngine:
    """获取全局触发器引擎实例。"""
    global _trigger_engine
    if _trigger_engine is None:
        _trigger_engine = TriggerEngine()
    return _trigger_engine
