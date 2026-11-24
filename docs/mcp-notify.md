# notify MCP Server

> 主动型 Agent 投递层：把 HITL 已批准的通知发到真实 channel。

---

## 工具列表（5 个）

| Tool | 描述 |
|---|---|
| `list_channels` | 列出已注册 channel + 可用性 |
| `dispatch_pending` | 拉所有 status=approved 的通知投递（可按 user_id 过滤） |
| `dispatch_one` | 单条投递（按 notification_id） |
| `test_channel` | 试投：合成消息测一个 channel（**不入库**） |
| `get_status` | notifications 表的状态计数（draft/approved/rejected/sent/failed） |

---

## Channel 抽象

每个 channel 实现 `BaseChannel` 接口：

```python
class BaseChannel(ABC):
    name: str
    @property
    def available(self) -> bool: ...
    async def send(self, *, user_id, title, body, metadata) -> dict: ...
```

内置 3 个：

| Channel | 配置 | 用途 |
|---|---|---|
| `console` | 永远可用 | dev 模式打印到 stderr |
| `file` | `NOTIFY_FILE_PATH`（默认 `./data/notifications.jsonl`） | 测试 + 审计追踪 |
| `email` | `NOTIFY_SMTP_*` 系列 + `NOTIFY_EMAIL_TO_BY_USER` | 真实邮件 |

新增 channel（如微信、Telegram、企业微信群）只要：
1. 实现 `BaseChannel`
2. 在 `notify/channels.py` 注册到 `_REGISTRY`

---

## Email 配置（可选）

```bash
# .env 片段
NOTIFY_SMTP_HOST=smtp.gmail.com
NOTIFY_SMTP_PORT=465
NOTIFY_SMTP_USER=you@gmail.com
NOTIFY_SMTP_PASSWORD=app-password
NOTIFY_SMTP_FROM=you@gmail.com
NOTIFY_SMTP_TLS=ssl                  # ssl | starttls
NOTIFY_EMAIL_TO_BY_USER='{"jason":"jason@example.com"}'
```

`available` 严格基于环境变量；不配就在 `list_channels` 中显示 `available=false`。  
`test_channel` 工具会返回明确 `{"ok":false,"error":"..."}` 而不是抛异常，便于 LLM agent 试错。

---

## 状态机 + 重试

```
   draft ──approve──▶ approved ──dispatch──▶ sent
                          │                    │
                          │  ChannelError       │
                          ▼                    ▼
                       attempts++           [terminal]
                        < 3 → 留 approved
                       == 3 → failed
```

- `MAX_ATTEMPTS = 3`
- 每次失败：`delivery_attempts++` + 写 `delivery_error`
- 第 3 次仍失败：`status = 'failed'`，自此 `dispatch_one` 拒绝处理（必须重新人工干预）
- 投递成功：`status='sent'`，`sent_at = now()`，`delivery_error = None`

测试覆盖：
- `test_dispatch_one_unknown_channel_marks_retry_then_failed`：3 次后变 failed
- `test_dispatch_pending_filters_by_user`：只拉指定 user 的 approved

---

## 与 scheduler 的协作

scheduler 的 `dispatch_pending` 是一个 **内置 job_kind**：

```python
# 注册一个每分钟自动派送的任务（开发可用）
register_job(
    name="global-dispatcher",
    user_id="*",                      # "*" 表示跨用户
    job_kind="dispatch_pending",
    interval_seconds=60,
    payload={"limit": 50},
)
```

到 W3+，前端有了之后改成事件驱动（approve 后立即触发）即可。

---

## 启动

```bash
# 直接（MCP stdio）
uv run python -m backend.app.mcp_servers.notify.server

# dev.sh
bash scripts/dev.sh mcp-inspect-notify   # 浏览器调试
bash scripts/dev.sh demo-w2-loop          # W2 闭环 demo
```

## Claude Desktop 接入

```json
{
  "mcpServers": {
    "notify": {
      "command": "uv",
      "args": ["--directory", "/path/to/HealthCoachAgent",
               "run", "python", "-m", "backend.app.mcp_servers.notify.server"],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "SQLITE_PATH": "/path/to/HealthCoachAgent/data/healthcoach.db",
        "NOTIFY_FILE_PATH": "/path/to/HealthCoachAgent/data/notifications.jsonl"
      }
    }
  }
}
```

---

## W2 闭环 demo 输出

```
$ bash scripts/dev.sh demo-w2-loop data/test_images/food.jpeg jason

[1/5] nutrition_v2_graph
      → 8 食材，1096 kcal
[2/5] registering job 'jason-daily-report'
[3/5] firing 'jason-daily-report' now
      → notification_id=1, status=draft
[4/5] HITL approve (channel=file)
      → status=draft → approved
[5/5] notify.dispatch_pending()
      ✅ id=1 status=sent attempts=0 channel=file

--- delivered (file: data/notifications.jsonl) ---
title: 📊 健康日报草稿 (2026-05-18, 近 7 天)
body : 你近7天只记录了1餐，总热量1096千卡，蛋白质77.9克，脂肪68.8克...
       明天建议尝试增加一餐，比如早餐加个鸡蛋和全麦面包，让营养更均衡。
```

---

## 测试覆盖（16 个）

```
tests/notify/test_channels_and_dispatcher.py    # 10
  - 三 channel send 行为 + 不可用判定 + 未知 channel 拒绝
  - dispatch_one happy / wrong-status / 重试到 failed
  - dispatch_pending 按 user 过滤

tests/mcp/test_notify_server.py                 # 6
  - list_tools / list_channels / test_channel
  - email 未配 → ok=false + 明确 error
  - dispatch_pending via MCP
  - get_status 状态计数
```

---

## v2 计划（W7+）

- [ ] 微信小程序订阅消息（template_id 模式）
- [ ] 反打扰：用户每日上限、静默时段、连续拒绝自动停用某 kind
- [ ] 紧急通道：心理 Coach 触发自伤红线时跳过 HITL 直接发
- [ ] 分布式去重（多进程时防止同一通知被发两次）
