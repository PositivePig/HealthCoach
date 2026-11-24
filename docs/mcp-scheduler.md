# scheduler MCP Server

> 主动型 Agent 的引擎：定时任务 + HITL 通知队列。

---

## 工具列表（8 个）

| Tool | 类型 | 描述 |
|---|---|---|
| `register_job` | write | 创建/更新一个定时任务（cron 或 interval） |
| `cancel_job` | write | 关闭一个任务（设 enabled=false） |
| `list_jobs` | read | 列出已注册任务（可按 user_id 过滤） |
| `run_job_now` | write | 立即执行一次（绕过下次触发时间） |
| `list_job_kinds` | read | 列出已注册的内置 job_kind |
| `list_notifications` | read | 列出用户通知（按 status 过滤） |
| `approve_notification` | write | HITL：草稿 → 已批准 |
| `reject_notification` | write | HITL：草稿 → 已拒绝 |

---

## 核心架构

```
       ┌────────────────────────────────────┐
       │     APScheduler AsyncIOScheduler    │
       │  (in-memory MemoryJobStore，进程内)  │
       └────┬────────────────────────────────┘
            │ trigger fires
            ▼
       ┌────────────────────────┐
       │  SchedulerCore._dispatch │
       └────┬───────────────────┘
            │ lookup job_kind
            ▼
       ┌────────────────────────┐
       │  registered job kind fn │  daily_report / protein_low_alert / ...
       └────┬───────────────────┘
            │
            ▼
       ┌────────────────────────┐
       │  Notification (status=draft) ─→ HITL inbox
       └────────────────────────┘

       Persistence layer:
       scheduled_jobs (ORM) ↔ scheduler (in-memory)
         on app start: load enabled rows → register triggers
         on register/cancel: write DB first, then mirror in-memory
```

**为什么不用 SQLAlchemyJobStore**：APScheduler 3.x 的 store 是同步并 pickle 闭包，与 async + typed payload 设计不匹配。用我们自己的 `ScheduledJob` ORM 表持久化，启动时重载即可。

---

## 内置 job_kind

### `daily_report`
- payload: `{"window_days": int = 1}`
- 行为：聚合用户近 N 天营养 → 调 LLM 生成日报文本 → 写 `Notification(kind="daily_report", status="draft")`
- 无 LLM key 时降级为模板版（仍出草稿）

### `protein_low_alert`
- payload: `{"days": int = 3, "target_protein_per_day": float = 60.0}`
- 行为：仅当近 N 天日均蛋白 < target 时才起草草稿（带阈值开关）

### 自己加 job_kind

```python
# backend/app/scheduler/jobs.py
from .core import register_job_kind

@register_job_kind("water_reminder")
async def water_reminder(user_id: str, payload: dict):
    ...
```

import 后立即生效，且 `register_job` 会在 `job_kind` 不在白名单时拒绝。

---

## HITL 状态机

```
   draft ──approve──▶ approved ──(notify MCP, W2 D4)──▶ sent
     │                                                    │
     ├──reject──▶ rejected                                ├──fail──▶ failed
```

- `approve` / `reject` 只能在 `status=draft` 时调用，否则返回 `not draft`
- `decided_at` 自动记录决定时间
- 拒绝时可附 reason，写入 `metadata_json.rejection_reason`

---

## 触发器规范

只支持两种触发器，参数互斥：

| 字段 | 含义 | 示例 |
|---|---|---|
| `cron_expr` | 标准 5 字段 cron | `"0 22 * * *"` 每天 22:00 |
| `interval_seconds` | 周期秒数 | `1800` 每 30 分钟 |

错误情况：
- 同时设 / 都不设 → `TriggerSpecError`
- cron 解析失败 → `TriggerSpecError`
- interval ≤ 0 → `TriggerSpecError`

时区固定 UTC（cron 时区由 APScheduler 默认 UTC 解释）。

---

## 启动方式

```bash
# 直接（MCP stdio）
uv run python -m backend.app.mcp_servers.scheduler.server

# dev.sh
bash scripts/dev.sh demo-scheduler        # 端到端 demo
bash scripts/dev.sh mcp-inspect-sched     # 浏览器调试
```

注意：scheduler **不会**在 server 进程启动时自动开始触发；首次 tool 调用时才 `start()`。这保证 stdio 模式下 stdout 干净（启动 banner 也不会喷出）。

---

## Claude Desktop 接入

```json
{
  "mcpServers": {
    "scheduler": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/HealthCoachAgent",
        "run", "python", "-m", "backend.app.mcp_servers.scheduler.server"
      ],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "SQLITE_PATH": "/path/to/HealthCoachAgent/data/healthcoach.db",
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

接入后可以直接对 Claude 说：
- "给 jason 注册一个每天 22 点的 daily_report"
- "立即跑一次 jason-daily-report"
- "看看 jason 的草稿"

Claude 会调用对应工具完成。

---

## 端到端 demo 输出（实跑）

```
$ bash scripts/dev.sh demo-scheduler jason

>>> registering job 'jason-daily-report' (cron 22:00 every day)
job_registered  kind=daily_report  next=2026-05-18T22:00:00+08:00
>>> firing it now (run_now)
daily_report_running days=7 user_id=jason
llm_call_ok model=deepseek-chat
daily_report_drafted notification_id=1

--- inbox: drafts ---
[id=1] 📊 健康日报草稿 (2026-05-18, 近 7 天)
嗨，这7天你吃了2餐，总热量1858kcal，蛋白质很足（145g），
但碳水偏低（75.9g）。明天可以试试在餐里加一小份红薯或全麦面包，
让能量更均衡哦！

--- approving draft id=1 (HITL) ---
ok → status=approved  (notify MCP will send in W2 D4)
```

---

## 测试覆盖（16 个）

```
tests/scheduler/test_scheduler_core.py     # 11
  - trigger 校验（cron / interval / 互斥 / 0 / bad）
  - registry：内置 kind 已加载
  - register 拒绝未知 kind
  - run_now → 起草 draft（含阈值正反向）
  - cancel + list_jobs

tests/mcp/test_scheduler_server.py         # 5
  - list_tools 全套
  - register → run → inbox → approve 工作流
  - reject 携带 reason
  - cancel
  - 未知 kind 错误响应
```

---

## v2 计划（W5+）

- [ ] 多机部署：把 in-memory 调度迁移到 Redis backed APScheduler
- [ ] 触发器扩展：DateTrigger（一次性）、event-based（数据库 NOTIFY）
- [ ] 反打扰：每日上限、静默时段、用户拒绝 N 次后自动停用
- [ ] 优先级队列：紧急通知（如健康异常）跳过 HITL 直接发
