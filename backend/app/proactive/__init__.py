"""主动型 Agent 模块。

提供主动触发、定时任务、HITL 确认、通知等能力。
"""

from __future__ import annotations

from .jobs import JobExecutor, get_job_executor
from .notifications import (
    NotificationChannel,
    NotificationPriority,
    NotificationService,
    get_notification_service,
    setup_notification_service,
)
from .triggers import TriggerEngine, get_trigger_engine
from .types import (
    HITLStatus,
    TriggerConfig,
    TriggerContext,
    TriggerKind,
    TriggerResult,
    TriggerStatus,
)

__all__ = [
    # 执行器
    "JobExecutor",
    "get_job_executor",
    # 触发器引擎
    "TriggerEngine",
    "get_trigger_engine",
    # 通知服务
    "NotificationChannel",
    "NotificationPriority",
    "NotificationService",
    "get_notification_service",
    "setup_notification_service",
    # 数据类型
    "TriggerConfig",
    "TriggerContext",
    "TriggerResult",
    "TriggerKind",
    "TriggerStatus",
    "HITLStatus",
]
