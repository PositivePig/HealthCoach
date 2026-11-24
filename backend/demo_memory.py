"""Demo: 三层记忆系统端到端测试。

测试完整链路：
1. 添加情景记忆（用餐/运动/体征）
2. 添加语义记忆（用户画像事实）
3. 设置过程记忆（沟通偏好）
4. 获取记忆上下文（模拟 Coach 调用）
5. 验证记忆上下文格式化为 LLM prompt

运行:
    cd /path/to/HealthCoachAgent
    uv run python backend/demo_memory.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.db import session_scope
from app.db.models import EpisodicEvent, ProceduralPreference
from sqlalchemy import delete, select

from app.memory import get_memory_context
from app.memory.episodic import EpisodicStore
from app.memory.semantic import Fact, FactTag, SemanticStore
from app.memory.procedural import ProceduralStore
from app.memory.types import (
    CommunicationStyle,
    DetailLevel,
    EventKind,
)


async def setup_test_data(session):
    """Set up test data for demo."""
    user_id = "demo_user_001"

    # 1. Episodic: add sample events
    logger.info("Setting up episodic events...")
    epi_store = EpisodicStore(session)

    # Add a meal event
    await epi_store.add(
        user_id=user_id,
        kind=EventKind.MEAL,
        payload={
            "total_kcal": 650,
            "total_protein_g": 35,
            "dishes": [{"name": "鸡胸肉沙拉", "weight_g": 200}],
        },
        summary="午餐：鸡胸肉沙拉 650 kcal",
    )

    # Add an activity event
    await epi_store.add(
        user_id=user_id,
        kind=EventKind.ACTIVITY,
        payload={
            "type": "跑步",
            "duration_min": 45,
            "distance_km": 5.2,
            "calories_burned": 420,
        },
        summary="傍晚跑步 5.2km / 45min",
    )

    # Add a vital event
    await epi_store.add(
        user_id=user_id,
        kind=EventKind.VITAL,
        payload={
            "weight_kg": 72.5,
            "sleep_min": 420,  # 7h
            "hrv_ms": 58,
            "mood": "good",
        },
        summary="体重 72.5kg / 睡眠 7h / HRV 58ms",
    )

    await session.commit()
    logger.success("Episodic events added")

    # 2. Semantic: add sample facts (gracefully handle Qdrant unavailable)
    logger.info("Setting up semantic facts...")
    sem_store = None
    try:
        sem_store = SemanticStore()
        facts = [
            Fact(
                user_id=user_id,
                fact="用户对花生过敏",
                tags=[FactTag.ALLERGY],
                confidence=1.0,
                source="user",
            ),
            Fact(
                user_id=user_id,
                fact="用户目标是减脂增肌",
                tags=[FactTag.GOAL],
                confidence=1.0,
                source="profile",
            ),
            Fact(
                user_id=user_id,
                fact="用户偏好简短回答",
                tags=[FactTag.PREFERENCE],
                confidence=0.9,
                source="inference",
            ),
        ]

        for fact in facts:
            fact_id = await sem_store.add_fact(fact)
            logger.info(f"Added fact: {fact.fact[:30]}... (id={fact_id})")

        logger.success("Semantic facts added")
    except Exception as e:
        logger.warning(f"SemanticStore unavailable (Qdrant not running?): {e}")
        logger.warning("Skipping semantic facts setup")
        sem_store = None

    # 3. Procedural: set preferences
    logger.info("Setting up procedural preferences...")
    proc_store = ProceduralStore(session)

    await proc_store.set_key(user_id, "tone", "warm")
    await proc_store.set_key(user_id, "detail_level", "medium")
    await proc_store.set_key(user_id, "use_emoji", "true")
    await proc_store.set_key(user_id, "version", "1")

    await session.commit()
    logger.success("Procedural preferences set")

    return user_id


async def demo_get_memory_context(user_id: str, session):
    """Demo: get_memory_context and format for prompt."""
    logger.info("Getting memory context...")

    # Simulate a user query
    query = "我昨天跑了 5 公里，今天应该吃什么？"

    ctx = await get_memory_context(
        user_id=user_id,
        session=session,
        query=query,
        episodic_days=7,
        semantic_k=5,
    )

    logger.info("Memory context retrieved")
    return ctx


async def demo_format_for_prompt(ctx):
    """Demo: format memory context for LLM prompt."""
    logger.info("Formatting memory context for prompt...")

    prompt_text = ctx.format_for_prompt()

    logger.info("Formatted prompt:")
    print("\n" + "="*60)
    print("【记忆上下文注入到 LLM Prompt】")
    print("="*60)
    print(prompt_text)
    print("="*60 + "\n")

    return prompt_text


async def demo_coach_integration(user_id: str, session):
    """Demo: simulate coach node with memory integration."""
    logger.info("Simulating coach node with memory integration...")

    # Get memory context (as a coach node would)
    query = "我最近训练量增加了，需要注意什么？"
    ctx = await get_memory_context(
        user_id=user_id,
        session=session,
        query=query,
        episodic_days=14,
        semantic_k=5,
    )

    # Format for prompt (as nutrition_coach_node / fitness_coach_node would)
    memory_block = ctx.format_for_prompt()

    # Simulate the user_payload that would be sent to LLM
    user_payload = f"""[记忆上下文]
    {memory_block}

    [用户画像]
    目标 减脂增肌 / 体重 72.5kg / 过敏 花生 / 病史 无

    [最近数据]
    近 7 天: 餐次 3, 日均 kcal 580, 日均蛋白 32g

    [用户问题]
    {query}
    """

    logger.info("Simulated user_payload for LLM:")
    print("\n" + "="*60)
    print("【模拟 LLM 输入（含记忆上下文）】")
    print("="*60)
    print(user_payload[:500] + "..." if len(user_payload) > 500 else user_payload)
    print("="*60 + "\n")

    return user_payload


async def cleanup_test_data(user_id: str, session):
    """Clean up test data."""
    logger.info("Cleaning up test data...")

    # Clean episodic events
    stmt = delete(EpisodicEvent).where(EpisodicEvent.user_id == user_id)
    await session.execute(stmt)

    # Delete procedural prefs
    stmt = delete(ProceduralPreference).where(ProceduralPreference.user_id == user_id)
    await session.execute(stmt)

    await session.commit()

    # Clean semantic facts (Qdrant) - gracefully handle unavailable Qdrant
    try:
        sem_store = SemanticStore()
        await sem_store.remove_all_for_user(user_id)
        logger.info("Semantic facts cleaned up")
    except Exception as e:
        logger.warning(f"Could not clean up semantic facts (Qdrant unavailable?): {e}")

    logger.success("Test data cleaned up")


async def main():
    """Run the demo."""
    logger.info("Starting memory system E2E demo...")

    # Use a test session
    async with session_scope() as session:
        user_id = "demo_user_001"

        try:
            # Setup
            await setup_test_data(session)

            # Demo 1: get_memory_context
            ctx = await demo_get_memory_context(user_id, session)

            # Demo 2: format_for_prompt
            await demo_format_for_prompt(ctx)

            # Demo 3: coach integration
            await demo_coach_integration(user_id, session)

            logger.success("Demo completed successfully!")

        finally:
            # Cleanup
            await cleanup_test_data(user_id, session)

    logger.info("Demo finished")


if __name__ == "__main__":
    asyncio.run(main())
