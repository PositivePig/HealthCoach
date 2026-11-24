"""主动型 Agent 数据类型定义。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TriggerKind(str, Enum):
    """触发器类型。"""
    TIMER = "timer"           # 定时触发（cron/interval）
    THRESHOLD = "threshold"   # 阈值触发（数据超限）
    EVENT = "event"           # 事件触发（特定事件发生）


class TriggerStatus(str, Enum):
    """触发器状态。"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class HITLStatus(str, Enum):
    """Human-In-The-Loop 状态。"""
    PENDING = "pending"       # 等待用户确认
    APPROVED = "approved"     # 用户批准
    REJECTED = "rejected"    # 用户拒绝
    BYPASSED = "bypassed"   # 无需确认（HITL未启用）


class TriggerConfig(BaseModel):
    """触发器配置。"""
    
    trigger_id: str = Field(..., description="触发器唯一ID")
    user_id: str = Field(..., description="用户ID")
    kind: TriggerKind = Field(..., description="触发器类型")
    
    # 通用字段
    name: str = Field(default="", description="触发器名称")
    description: str = Field(default="", description="触发器描述")
    enabled: bool = Field(default=True, description="是否启用")
    
    # 定时触发器字段
    cron_expr: Optional[str] = Field(default=None, description="Cron表达式")
    interval_seconds: Optional[int] = Field(default=None, description="间隔时间（秒）")
    
    # 阈值触发器字段
    metric: Optional[str] = Field(default=None, description="监控指标名称")
    threshold_value: Optional[float] = Field(default=None, description="阈值")
    threshold_direction: Optional[str] = Field(
        default=None,
        description="阈值方向：below/above",
    )
    
    # 事件触发器字段
    event_type: Optional[str] = Field(default=None, description="监听的事件类型")
    
    # HITL 配置
    hitl_enabled: bool = Field(default=True, description="是否启用HITL")
    
    # 元数据
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="更新时间",
    )
    
    class Config:
        use_enum_values = True
    
    def validate_config(self) -> None:
        """验证配置合法性。"""
        if self.kind == TriggerKind.TIMER:
            if not self.cron_expr and not self.interval_seconds:
                raise ValueError("Timer trigger must have cron_expr or interval_seconds")
            if self.cron_expr and self.interval_seconds:
                raise ValueError("Timer trigger cannot have both cron_expr and interval_seconds")
        
        elif self.kind == TriggerKind.THRESHOLD:
            if not self.metric:
                raise ValueError("Threshold trigger must have metric")
            if self.threshold_value is None:
                raise ValueError("Threshold trigger must have threshold_value")
            if self.threshold_direction not in ("below", "above"):
                raise ValueError("threshold_direction must be 'below' or 'above'")
        
        elif self.kind == TriggerKind.EVENT:
            if not self.event_type:
                raise ValueError("Event trigger must have event_type")


class TriggerContext(BaseModel):
    """触发器触发时的上下文。"""
    
    trigger_id: str = Field(..., description="触发器ID")
    user_id: str = Field(..., description="用户ID")
    kind: TriggerKind = Field(..., description="触发器类型")
    triggered_at: datetime = Field(..., description="触发时间")
    
    # 触发时的数据快照
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="触发元数据",
    )
    
    # HITL 状态
    hitl_enabled: bool = Field(default=True, description="是否启用HITL")
    hitl_status: HITLStatus = Field(
        default=HITLStatus.PENDING,
        description="HITL状态",
    )
    
    # 用户响应
    user_response: Optional[str] = Field(default=None, description="用户响应内容")
    responded_at: Optional[datetime] = Field(default=None, description="响应时间")
    
    class Config:
        use_enum_values = True
    
    def to_prompt(self) -> str:
        """格式化为LLM Prompt片段。"""
        # 兼容 use_enum_values=True 的情况
        kind_value = self.kind if isinstance(self.kind, str) else self.kind.value
        
        lines = [
            f"[主动提醒 - {kind_value}]",
            f"触发时间: {self.triggered_at.strftime('%Y-%m-%d %H:%M')}",
        ]
        
        if self.metadata:
            lines.append("触发数据:")
            for key, value in self.metadata.items():
                lines.append(f"  - {key}: {value}")
        
        if self.hitl_enabled:
            # 兼容 use_enum_values=True 的情况
            hitl_value = self.hitl_status if isinstance(self.hitl_status, str) else self.hitl_status.value
            lines.append(f"HITL状态: {hitl_value}")
            
            # 检查是否为pending状态
            pending_value = HITLStatus.PENDING.value
            if self.hitl_status == pending_value or self.hitl_status == HITLStatus.PENDING:
                lines.append("等待用户确认...")
        
        return "\n".join(lines)


class TriggerResult(BaseModel):
    """触发器执行结果。"""
    
    trigger_id: str = Field(..., description="触发器ID")
    user_id: str = Field(..., description="用户ID")
    triggered_at: datetime = Field(..., description="触发时间")
    
    context: TriggerContext = Field(..., description="触发上下文")
    
    # 执行结果
    hitl_status: HITLStatus = Field(
        default=HITLStatus.BYPASSED,
        description="HITL状态",
    )
    executed: bool = Field(default=False, description="是否已执行")
    execution_result: Optional[str] = Field(default=None, description="执行结果")
    
    # 通知状态
    notified: bool = Field(default=False, description="是否已通知用户")
    notified_at: Optional[datetime] = Field(default=None, description="通知时间")
    notification_channel: Optional[str] = Field(default=None, description="通知渠道")
    
    class Config:
        use_enum_values = True
