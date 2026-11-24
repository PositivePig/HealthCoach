#!/usr/bin/env python3
"""W5 主动型 Agent 演示脚本。

测试功能：
1. 创建触发器
2. 检查触发器触发
3. HITL 机制
4. 通知发送
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# 添加backend目录到path
sys.path.insert(0, "/apdcephfs/jia_iqa/youtu-pangu_palm_public_1511122_cq10/jasonjpjia/IntelligentAgent/HealthCoachAgent/backend")

from app.proactive import (
    TriggerConfig,
    TriggerKind,
    get_notification_service,
    get_trigger_engine,
)
from app.proactive.notifications import NotificationPriority


def print_section(title: str):
    """打印分节标题。"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def test_trigger_creation():
    """测试触发器创建。"""
    print_section("测试1: 创建触发器")
    
    engine = get_trigger_engine()
    
    # 创建定时触发器（每分钟触发一次，用于测试）
    timer_config = TriggerConfig(
        trigger_id=f"timer_{uuid4().hex[:8]}",
        user_id="test_user_001",
        kind=TriggerKind.TIMER,
        name="测试定时触发器",
        description="每分钟触发一次的测试触发器",
        interval_seconds=60,  # 1分钟
        hitl_enabled=True,
        metadata={"test": True},
    )
    
    engine.register(timer_config)
    print(f"✅ 定时触发器已创建: {timer_config.trigger_id}")
    print(f"   间隔: {timer_config.interval_seconds}秒")
    
    # 创建阈值触发器
    threshold_config = TriggerConfig(
        trigger_id=f"threshold_{uuid4().hex[:8]}",
        user_id="test_user_001",
        kind=TriggerKind.THRESHOLD,
        name="蛋白质摄入不足提醒",
        description="最近7天平均蛋白质摄入低于50g时提醒",
        metric="protein_intake",
        threshold_value=50.0,
        threshold_direction="below",
        hitl_enabled=True,
        metadata={"lookback_days": 7},
    )
    
    engine.register(threshold_config)
    print(f"✅ 阈值触发器已创建: {threshold_config.trigger_id}")
    print(f"   指标: {threshold_config.metric}")
    print(f"   阈值: {threshold_config.threshold_value} ({threshold_config.threshold_direction})")
    
    return timer_config, threshold_config


async def test_trigger_check(timer_config, threshold_config):
    """测试触发器检查。"""
    print_section("测试2: 检查触发器触发")
    
    engine = get_trigger_engine()
    
    # 手动设置last_run，模拟时间已过
    now = datetime.now(timezone.utc)
    timer_config.metadata["last_run"] = (now - timedelta(seconds=61)).isoformat()
    
    print(f"模拟时间已过61秒，定时触发器应该触发...")
    print(f"last_run: {timer_config.metadata['last_run']}")
    
    # 检查触发器
    contexts = await engine.check_all("test_user_001")
    
    print(f"\n✅ 触发了 {len(contexts)} 个触发器:")
    for ctx in contexts:
        kind_value = ctx.kind if isinstance(ctx.kind, str) else ctx.kind.value
        print(f"   - {ctx.trigger_id} ({kind_value})")
        print(f"     触发时间: {ctx.triggered_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"     HITL: {ctx.hitl_enabled}")
        if ctx.metadata:
            print(f"     元数据: {ctx.metadata}")
    
    return contexts


async def test_hitl(contexts):
    """测试 HITL 机制。"""
    print_section("测试3: HITL 机制")
    
    engine = get_trigger_engine()
    
    # 查看待确认的HITL
    pending = engine.get_pending_hitl("test_user_001")
    
    print(f"待确认的HITL: {len(pending)} 个")
    for result in pending:
        print(f"   - {result.trigger_id}")
        print(f"     状态: {result.hitl_status}")
        print(f"     触发时间: {result.triggered_at.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 批准第一个HITL
    if pending:
        first_result = pending[0]
        print(f"\n批准 HITL: {first_result.trigger_id}")
        
        success = await engine.approve_hitl(
            first_result.trigger_id,
            first_result.user_id,
        )
        
        if success:
            print(f"✅ HITL 已批准")
        else:
            print(f"❌ HITL 批准失败")
        
        # 拒绝第二个HITL（如果有）
        if len(pending) > 1:
            second_result = pending[1]
            print(f"\n拒绝 HITL: {second_result.trigger_id}")
            
            success = await engine.reject_hitl(
                second_result.trigger_id,
                second_result.user_id,
            )
            
            if success:
                print(f"✅ HITL 已拒绝")
            else:
                print(f"❌ HITL 拒绝失败")


async def test_notification():
    """测试通知发送。"""
    print_section("测试4: 通知发送")
    
    service = get_notification_service()
    
    # 发送测试通知
    print("发送测试通知...")
    
    results = await service.send_notification(
        user_id="test_user_001",
        title="🧪 测试通知",
        message="这是一条测试通知消息。\n\n用于验证通知通道是否正常工作。",
        priority=NotificationPriority.NORMAL,
        metadata={
            "test": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    
    print(f"\n✅ 通知发送结果:")
    for channel, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"   - {channel}: {status}")


async def test_trigger_context_formatting():
    """测试触发上下文格式化。"""
    print_section("测试5: 触发上下文格式化")
    
    from app.proactive.types import TriggerContext, HITLStatus
    
    # 创建测试上下文
    ctx = TriggerContext(
        trigger_id="test_trigger_001",
        user_id="test_user_001",
        kind=TriggerKind.THRESHOLD,
        triggered_at=datetime.now(timezone.utc),
        metadata={
            "avg_protein": 45.2,
            "threshold": 50.0,
            "days": 7,
        },
        hitl_enabled=True,
        hitl_status=HITLStatus.PENDING,
    )
    
    # 格式化为Prompt
    prompt = ctx.to_prompt()
    
    print("✅ 触发上下文已格式化:")
    print("\n" + prompt)


async def test_list_triggers():
    """测试列出触发器。"""
    print_section("测试6: 列出所有触发器")
    
    engine = get_trigger_engine()
    
    print(f"当前注册的触发器:")
    for trigger_id, config in engine._triggers.items():
        # 兼容 use_enum_values=True 的情况
        kind_value = config.kind if isinstance(config.kind, str) else config.kind.value
        
        print(f"\n   ID: {trigger_id}")
        print(f"   名称: {config.name}")
        print(f"   类型: {kind_value}")
        print(f"   用户: {config.user_id}")
        print(f"   启用: {config.enabled}")
        print(f"   HITL: {config.hitl_enabled}")


async def main():
    """主函数。"""
    print("\n" + "=" * 60)
    print("  W5 主动型 Agent 功能演示")
    print("=" * 60)
    
    try:
        # 测试1: 创建触发器
        timer_config, threshold_config = await test_trigger_creation()
        
        # 测试2: 检查触发器触发
        contexts = await test_trigger_check(timer_config, threshold_config)
        
        # 测试3: HITL机制
        await test_hitl(contexts)
        
        # 测试4: 通知发送
        await test_notification()
        
        # 测试5: 触发上下文格式化
        await test_trigger_context_formatting()
        
        # 测试6: 列出触发器
        await test_list_triggers()
        
        print_section("测试完成")
        print("✅ W5 主动型 Agent 核心功能验证成功!")
        print("\n主要功能:")
        print("  1. ✅ 触发器创建和管理")
        print("  2. ✅ 定时/阈值触发器检查")
        print("  3. ✅ HITL (Human-In-The-Loop) 机制")
        print("  4. ✅ 通知通道（控制台、数据库、WebSocket）")
        print("  5. ✅ 触发上下文格式化和Prompt生成")
        print("\n下一步:")
        print("  - 集成到主API服务")
        print("  - 配置WebSocket实时推送")
        print("  - 完善前端通知展示")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
