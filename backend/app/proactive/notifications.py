"""主动型 Agent 通知通道。

支持多种通知方式：
1. 控制台输出（开发环境）
2. 数据库存储（用户稍后查看）
3. WebSocket推送（实时通知）
4. 未来扩展：邮件、短信、推送通知等
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from ..db.engine import session_scope as async_session
from .types import TriggerContext, TriggerResult


class NotificationPriority(str, Enum):
    """通知优先级。"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationChannel:
    """通知通道基类。"""
    
    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self.enabled = True
        
    async def send(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """发送通知。返回是否成功。"""
        raise NotImplementedError
    
    async def batch_send(
        self,
        notifications: List[Dict[str, Any]],
    ) -> List[bool]:
        """批量发送通知。"""
        results = []
        for notif in notifications:
            result = await self.send(**notif)
            results.append(result)
        return results


class ConsoleNotificationChannel(NotificationChannel):
    """控制台通知通道（开发环境使用）。"""
    
    def __init__(self):
        super().__init__("console")
        
    async def send(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """在控制台打印通知。"""
        priority_emoji = {
            NotificationPriority.LOW: "💤",
            NotificationPriority.NORMAL: "📢",
            NotificationPriority.HIGH: "⚠️",
            NotificationPriority.URGENT: "🚨",
        }
        
        emoji = priority_emoji.get(priority, "📢")
        
        print("\n" + "=" * 60)
        print(f"{emoji} 通知 - {title}")
        print("=" * 60)
        print(f"用户: {user_id}")
        print(f"优先级: {priority.value}")
        print(f"时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("-" * 60)
        print(message)
        if metadata:
            print("-" * 60)
            print("元数据:")
            print(json.dumps(metadata, indent=2, ensure_ascii=False))
        print("=" * 60 + "\n")
        
        logger.info(
            "notification_sent",
            channel="console",
            user_id=user_id,
            title=title,
            priority=priority.value,
        )
        
        return True


class DatabaseNotificationChannel(NotificationChannel):
    """数据库通知通道（存储到数据库，用户稍后查看）。"""
    
    def __init__(self):
        super().__init__("database")
        
    async def send(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """将通知存储到数据库。"""
        try:
            async with async_session() as session:
                # 这里应该有一个Notification模型
                # 暂时用print模拟
                logger.info(
                    "notification_stored",
                    channel="database",
                    user_id=user_id,
                    title=title,
                    priority=priority.value,
                )
                
                # TODO: 实际实现需要创建Notification模型
                # notification = Notification(
                #     user_id=user_id,
                #     title=title,
                #     message=message,
                #     priority=priority.value,
                #     metadata=json.dumps(metadata) if metadata else None,
                #     read=False,
                #     created_at=datetime.now(timezone.utc),
                # )
                # session.add(notification)
                # await session.commit()
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to store notification: {e}")
            return False


class WebSocketNotificationChannel(NotificationChannel):
    """WebSocket通知通道（实时推送给用户）。"""
    
    def __init__(self, websocket_manager=None):
        super().__init__("websocket")
        self.websocket_manager = websocket_manager
        
    async def send(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """通过WebSocket实时推送通知。"""
        if not self.websocket_manager:
            logger.warning("WebSocket manager not configured")
            return False
        
        try:
            notification_data = {
                "type": "notification",
                "title": title,
                "message": message,
                "priority": priority.value,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # 推送给特定用户
            await self.websocket_manager.send_to_user(
                user_id=user_id,
                data=notification_data,
            )
            
            logger.info(
                "notification_pushed",
                channel="websocket",
                user_id=user_id,
                title=title,
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to push notification: {e}")
            return False


class NotificationService:
    """通知服务，管理多个通知通道。"""
    
    def __init__(self):
        self.channels: Dict[str, NotificationChannel] = {}
        self.default_channels = ["console"]  # 默认使用的通道
        
    def register_channel(self, channel: NotificationChannel) -> None:
        """注册通知通道。"""
        self.channels[channel.channel_name] = channel
        logger.info(f"Notification channel registered: {channel.channel_name}")
        
    def unregister_channel(self, channel_name: str) -> None:
        """注销通知通道。"""
        if channel_name in self.channels:
            del self.channels[channel_name]
            logger.info(f"Notification channel unregistered: {channel_name}")
        
    async def send_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """通过多个通道发送通知。返回每个通道的发送结果。"""
        if channels is None:
            channels = self.default_channels
        
        results = {}
        for channel_name in channels:
            if channel_name not in self.channels:
                logger.warning(f"Notification channel not found: {channel_name}")
                results[channel_name] = False
                continue
            
            channel = self.channels[channel_name]
            if not channel.enabled:
                logger.debug(f"Notification channel disabled: {channel_name}")
                results[channel_name] = False
                continue
            
            try:
                success = await channel.send(
                    user_id=user_id,
                    title=title,
                    message=message,
                    priority=priority,
                    metadata=metadata,
                )
                results[channel_name] = success
            except Exception as e:
                logger.error(f"Error sending notification via {channel_name}: {e}")
                results[channel_name] = False
        
        return results
    
    async def send_trigger_notification(
        self,
        result: TriggerResult,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """发送触发器通知。"""
        ctx = result.context
        
        # 根据触发器类型生成通知内容
        if ctx.kind.value == "timer":
            title = f"⏰ 定时提醒：{ctx.metadata.get('job_name', '定时任务')}"
        elif ctx.kind.value == "threshold":
            title = "⚠️ 阈值告警"
        elif ctx.kind.value == "event":
            title = "📢 事件通知"
        else:
            title = "🔔 主动提醒"
        
        # 生成通知消息
        message = ctx.to_prompt()
        
        if result.execution_result:
            message += f"\n\n执行结果:\n{result.execution_result}"
        
        # 确定优先级
        if ctx.kind.value == "threshold":
            priority = NotificationPriority.HIGH
        else:
            priority = NotificationPriority.NORMAL
        
        return await self.send_notification(
            user_id=result.user_id,
            title=title,
            message=message,
            priority=priority,
            metadata={
                "trigger_id": result.trigger_id,
                "trigger_kind": ctx.kind.value,
                "hitl_status": result.hitl_status,
                "executed": result.executed,
            },
            channels=channels,
        )


# 全局通知服务实例
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """获取全局通知服务实例。"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
        # 注册默认通道
        _notification_service.register_channel(ConsoleNotificationChannel())
        _notification_service.register_channel(DatabaseNotificationChannel())
    return _notification_service


def setup_notification_service(
    websocket_manager=None,
    enable_console: bool = True,
    enable_database: bool = True,
    enable_websocket: bool = False,
) -> NotificationService:
    """配置并获取通知服务。"""
    global _notification_service
    _notification_service = NotificationService()
    
    if enable_console:
        _notification_service.register_channel(ConsoleNotificationChannel())
    
    if enable_database:
        _notification_service.register_channel(DatabaseNotificationChannel())
    
    if enable_websocket and websocket_manager:
        channel = WebSocketNotificationChannel(websocket_manager)
        _notification_service.register_channel(channel)
    
    return _notification_service
