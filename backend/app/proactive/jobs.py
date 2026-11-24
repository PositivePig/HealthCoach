"""主动型 Agent 定时任务包装。

基于 APScheduler 包装定时任务，与触发器系统集成。
支持：
1. Cron 表达式触发
2. Interval 间隔触发
3. 与 HITL 机制集成
4. 任务执行历史记录
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from .types import (
    HITLStatus,
    TriggerConfig,
    TriggerContext,
    TriggerKind,
    TriggerResult,
)
from .triggers import TriggerEngine, get_trigger_engine


class JobExecutor:
    """定时任务执行器。
    
    负责：
    1. 注册和管理定时任务
    2. 执行任务逻辑
    3. 与 HITL 机制集成
    4. 记录执行历史
    """
    
    def __init__(self, scheduler: AsyncIOScheduler):
        self._scheduler = scheduler
        self._trigger_engine = get_trigger_engine()
        self._job_registry: Dict[str, Callable] = {}
        
        logger.info("job_executor_initialized")
    
    def register_job(
        self,
        job_id: str,
        trigger_config: TriggerConfig,
        job_func: Callable,
    ) -> None:
        """注册一个定时任务。"""
        if job_id in self._job_registry:
            logger.warning(f"Job {job_id} already registered, overwriting")
        
        # 注册到任务注册表
        self._job_registry[job_id] = job_func
        
        # 注册到触发器引擎
        self._trigger_engine.register(trigger_config)
        
        # 注册到 APScheduler
        if trigger_config.cron_expr:
            trigger = CronTrigger.from_crontab(trigger_config.cron_expr)
        elif trigger_config.interval_seconds:
            trigger = IntervalTrigger(seconds=trigger_config.interval_seconds)
        else:
            raise ValueError("Trigger must have cron_expr or interval_seconds")
        
        self._scheduler.add_job(
            func=self._execute_job,
            trigger=trigger,
            args=[job_id, trigger_config.user_id],
            id=job_id,
            name=trigger_config.name,
            replace_existing=True,
        )
        
        logger.info(
            "job_registered",
            job_id=job_id,
            user_id=trigger_config.user_id,
            trigger=trigger_config.cron_expr or f"interval:{trigger_config.interval_seconds}s",
        )
    
    def unregister_job(self, job_id: str) -> None:
        """注销一个定时任务。"""
        if job_id in self._job_registry:
            del self._job_registry[job_id]
            
            # 从调度器移除
            try:
                self._scheduler.remove_job(job_id)
            except Exception as e:
                logger.warning(f"Failed to remove job {job_id}: {e}")
            
            # 从触发器引擎移除
            self._trigger_engine.unregister(job_id)
            
            logger.info("job_unregistered", job_id=job_id)
    
    async def run_job_now(self, job_id: str, user_id: str) -> Optional[TriggerResult]:
        """立即执行一个任务（用于测试）。"""
        if job_id not in self._job_registry:
            logger.error(f"Job {job_id} not found")
            return None
        
        return await self._execute_job(job_id, user_id)
    
    async def _execute_job(self, job_id: str, user_id: str) -> TriggerResult:
        """执行任务逻辑。"""
        logger.info("job_execution_started", job_id=job_id, user_id=user_id)
        
        # 获取触发器配置
        trigger_config = self._trigger_engine._triggers.get(job_id)
        if not trigger_config:
            logger.error(f"Trigger config not found for job {job_id}")
            return None
        
        # 生成触发上下文
        ctx = TriggerContext(
            trigger_id=job_id,
            user_id=user_id,
            kind=TriggerKind.TIMER,
            triggered_at=datetime.now(timezone.utc),
            hitl_enabled=trigger_config.hitl_enabled,
            metadata={
                "job_name": trigger_config.name,
                "scheduled": True,
            },
        )
        
        # 创建执行结果
        result = TriggerResult(
            trigger_id=job_id,
            user_id=user_id,
            triggered_at=ctx.triggered_at,
            context=ctx,
            hitl_status="pending" if trigger_config.hitl_enabled else "bypassed",
        )
        
        # 如果启用 HITL，等待用户确认
        if trigger_config.hitl_enabled:
            logger.info("hitl_pending", job_id=job_id)
            # TODO: 这里应该暂停，等待用户通过 API 确认
            # 暂时假设用户会批准
            # await self._wait_for_hitl_approval(job_id, user_id)
        
        # 执行任务函数
        try:
            job_func = self._job_registry.get(job_id)
            if job_func:
                execution_result = await job_func(user_id, ctx)
                result.execution_result = str(execution_result)
                result.executed = True
                
                logger.info(
                    "job_execution_completed",
                    job_id=job_id,
                    result=execution_result,
                )
            else:
                logger.error(f"Job function not found for {job_id}")
        
        except Exception as e:
            logger.error(f"Job execution failed: {e}")
            result.execution_result = f"Error: {e}"
        
        return result
    
    async def _wait_for_hitl_approval(
        self, job_id: str, user_id: str, timeout: int = 300
    ) -> bool:
        """等待用户 HITL 确认（简化版）。"""
        # 简化实现：直接批准
        # 实际应该：
        # 1. 将 result 存入数据库
        # 2. 通过通知系统告知用户
        # 3. 等待用户通过 API 调用 approve_hitl / reject_hitl
        # 4. 设置超时
        
        logger.info("hitl_auto_approving", job_id=job_id)
        await self._trigger_engine.approve_hitl(job_id, user_id)
        return True


# 预定义任务函数
async def daily_report_job(user_id: str, ctx: TriggerContext) -> str:
    """每日报告任务。"""
    logger.info("daily_report_job_started", user_id=user_id)
    
    # 查询今天的数据
    from ..db.models import Meal, Activity, Vital
    from ..db.session import async_session
    
    async with async_session() as session:
        # 查询今日餐次
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        meals = await session.execute(
            """
            SELECT COUNT(*) as cnt, AVG(total_kcal) as avg_kcal, AVG(total_protein_g) as avg_protein
            FROM meals
            WHERE user_id = :user_id AND ts >= :today_start
            """,
            {"user_id": user_id, "today_start": today_start},
        )
        meal_data = meals.first()
        
        # 查询今日运动
        activities = await session.execute(
            """
            SELECT COUNT(*) as cnt, SUM(duration_min) as total_min, SUM(calories_burned) as total_cal
            FROM activities
            WHERE user_id = :user_id AND ts >= :today_start
            """,
            {"user_id": user_id, "today_start": today_start},
        )
        activity_data = activities.first()
        
        # 查询今日体征
        vitals = await session.execute(
            """
            SELECT AVG(weight_kg) as avg_weight, AVG(sleep_min) as avg_sleep, AVG(hrv_ms) as avg_hrv
            FROM vitals
            WHERE user_id = :user_id AND ts >= :today_start
            """,
            {"user_id": user_id, "today_start": today_start},
        )
        vital_data = vitals.first()
    
    # 生成报告
    report_lines = ["📊 今日健康报告", "=" * 40]
    
    if meal_data and meal_data.cnt > 0:
        report_lines.append(f"🍽️  餐次: {meal_data.cnt} 次")
        report_lines.append(f"   平均热量: {meal_data.avg_kcal:.0f} kcal")
        report_lines.append(f"   平均蛋白质: {meal_data.avg_protein:.1f} g")
    else:
        report_lines.append("🍽️  今日尚未记录饮食")
    
    if activity_data and activity_data.cnt > 0:
        report_lines.append(f"🏃 运动: {activity_data.cnt} 次")
        report_lines.append(f"   总时长: {activity_data.total_min:.0f} 分钟")
        report_lines.append(f"   消耗热量: {activity_data.total_cal:.0f} kcal")
    else:
        report_lines.append("🏃 今日尚未记录运动")
    
    if vital_data and vital_data.avg_weight:
        report_lines.append(f"💤 体重: {vital_data.avg_weight:.1f} kg")
        if vital_data.avg_sleep:
            report_lines.append(f"   睡眠: {vital_data.avg_sleep:.0f} 分钟")
        if vital_data.avg_hrv:
            report_lines.append(f"   HRV: {vital_data.avg_hrv:.0f} ms")
    
    report = "\n".join(report_lines)
    logger.info("daily_report_generated", user_id=user_id, report_length=len(report))
    
    return report


async def protein_low_alert_job(user_id: str, ctx: TriggerContext) -> str:
    """蛋白质不足提醒任务。"""
    logger.info("protein_low_alert_job_started", user_id=user_id)
    
    avg_protein = ctx.metadata.get("avg_protein", 0)
    threshold = ctx.metadata.get("threshold", 0)
    
    message = f"⚠️  蛋白质摄入不足提醒\n\n"
    message += f"最近 7 天平均蛋白质摄入: {avg_protein:.1f} g\n"
    message += f"推荐目标: {threshold:.1f} g\n"
    message += f"\n建议增加富含蛋白质的食物：鸡胸肉、鱼、豆腐、鸡蛋..."
    
    logger.info("protein_low_alert_generated", user_id=user_id, avg_protein=avg_protein)
    
    return message


# 全局执行器实例
_job_executor: Optional[JobExecutor] = None


def get_job_executor(scheduler: AsyncIOScheduler = None) -> JobExecutor:
    """获取全局任务执行器实例。"""
    global _job_executor
    if _job_executor is None:
        if scheduler is None:
            raise ValueError("Scheduler must be provided for first initialization")
        _job_executor = JobExecutor(scheduler)
    return _job_executor
