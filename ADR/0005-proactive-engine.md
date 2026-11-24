# ADR 0005 - 主动型 Agent 引擎设计

- **日期**：2026-05-18
- **状态**：Accepted

## 背景

绝大多数 Agent 是 **被动响应式**——用户问，它答。本项目的核心差异化是 **主动型**：

> Agent 应该 **观察、思考、主动行动**，而不是只在用户来戳它时才工作。

这是 2026 年 Agent 学界 / 业界共同关注的方向（proactive agents、scheduled agents、event-driven agents），但落地少。

## 决策

设计一个 **三类触发器** 的 Proactive Engine，统一通过调用 Supervisor 入口完成主动任务，复用所有现有能力。

### 三类触发器

#### 1. 定时触发器（ScheduledTrigger）
基于 cron / interval 的固定调度。

| 任务 | 频率 |
|---|---|
| 每日报告 | `0 22 * * *` |
| 每周报告 | `0 20 * * 0` |
| 早安提醒（如开启） | `0 8 * * *` |
| 周一计划提醒 | `0 21 * * 0` |

#### 2. 阈值触发器（ThresholdTrigger）
扫描数据，命中规则即触发。

| 规则 | 触发 |
|---|---|
| 连续 3 天蛋白质 < 目标 70% | 营养教练介入 |
| 连续 5 天 0 运动 | 健身教练介入 |
| 连续 3 天睡眠 < 6h | 心理教练介入 |
| 单日水分 < 1L 且 16:00 | 提醒喝水 |

扫描频率：每 30 分钟。

#### 3. 事件触发器（EventTrigger）
数据库写入触发 / 应用层事件。

| 事件 | 触发 |
|---|---|
| 体重单日变化 > 1kg | 数据分析师评估异常 |
| 用户首次记录某新食物 | 营养教练补充建议 |
| 距上次互动 > 7 天 | 关怀消息 |
| 用户标记"今天压力大" | 心理教练主动跟进 |

## 架构

```
┌─────────────────────────────────────────────────┐
│              Proactive Engine                   │
│                                                 │
│   APScheduler（定时） ──┐                        │
│                       ▼                         │
│   Threshold Scanner ──┤                         │
│                       ├──► Trigger Bus ──┐      │
│   Event Listener ────┘                  ▼      │
│   (Postgres LISTEN/NOTIFY)        Supervisor    │
│                                   .invoke({     │
│                                     intent:     │
│                                     "alert",    │
│                                     trigger,    │
│                                     payload     │
│                                   })            │
└─────────────────────────────────────────────────┘
              │
              ▼
        LangGraph Run
              │
              ▼
        Coach 起草消息
              │
              ▼
        HITL: interrupt 等待用户确认
              │ (用户在前端点确认)
              ▼
        notify MCP 发送
              │
              ▼
        Postgres notifications 表更新 status=sent
```

## 核心抽象

```python
# backend/app/proactive/triggers.py
from abc import ABC, abstractmethod

class Trigger(ABC):
    name: str
    
    @abstractmethod
    async def check(self) -> list[FireEvent]:
        """返回所有需要触发的事件（每个用户一个）"""
    
    async def fire(self, event: FireEvent):
        await supervisor_app.ainvoke({
            "intent": "alert",
            "user_id": event.user_id,
            "trigger_name": self.name,
            "payload": event.payload,
        }, config={"configurable": {"thread_id": f"alert-{event.user_id}-{ts}"}})

class ProteinLowStreak(Trigger):
    name = "protein_low_streak"
    async def check(self):
        # 参数化 SQL 查询所有蛋白连续 3 天不足的用户
        users = await db.fetch("""
            WITH daily AS (
                SELECT user_id, date_trunc('day', ts) AS d, SUM(total_p) p
                FROM meals WHERE ts > now() - interval '4 days'
                GROUP BY user_id, d
            )
            ...
        """)
        return [FireEvent(...) for u in users]
```

```python
# backend/app/proactive/jobs.py
scheduler = AsyncIOScheduler()

# 定时
scheduler.add_job(daily_report_job, CronTrigger(hour=22))
scheduler.add_job(weekly_report_job, CronTrigger(day_of_week=0, hour=20))

# 阈值（统一定时扫描）
async def threshold_scan():
    for trigger in [ProteinLowStreak(), ZeroActivityStreak(), 
                    LowSleepStreak(), WaterReminder()]:
        events = await trigger.check()
        for e in events:
            await trigger.fire(e)

scheduler.add_job(threshold_scan, IntervalTrigger(minutes=30))
```

## HITL（关键设计）

**主动消息发送前必须用户确认**——否则 Agent 容易"打扰过度"。

实现方式：
1. Coach 起草消息后写入 `notifications` 表（status=`draft`）
2. 前端 inbox 看到 draft，用户点"批准/编辑/丢弃"
3. 批准 → notify MCP 发送 → status=`sent`
4. 编辑 → 用户改完发送
5. 丢弃 → status=`rejected`，Agent 学到"用户不喜欢这种提醒"（写入 Procedural）

也可配置"自动批准白名单"（如每日报告默认自动发）。

## 反打扰机制

- 每个用户每天最多收到 **5 条主动消息**（可配置）
- 同类型 24h 内不重复
- 静默时段：22:00 - 8:00 不打扰（除每日报告外）
- 学习用户反馈：3 次拒绝后停用该触发器一周

## 后果

### 优点
- ✅ 真正"活的"Agent
- ✅ 可观测：所有触发都走 Supervisor，全链路 trace
- ✅ 可控：HITL + 反打扰
- ✅ 可扩展：加新触发器只是加一个类

### 缺点
- ⚠️ 复杂度：调度器 + 扫描器 + HITL，工程量大
- ⚠️ 误触发风险 → 评估集必须含主动场景

## 落地节奏

- W5 全周专攻：D1-2 触发器框架，D3 定时任务，D4 阈值，D5 HITL，D6-7 反打扰 + 测试

## 失败模式 & 缓解

| 失败 | 缓解 |
|---|---|
| 调度器进程挂 | systemd / docker restart=always + 启动时补齐遗漏任务 |
| 阈值扫描压力大 | 写好索引；分批；只扫近 N 天数据 |
| 用户烦了 | 反打扰 + 学习反馈 + 一键关闭主动模式 |
| 凌晨触发用户被吵醒 | 静默时段 + 时区识别 |
