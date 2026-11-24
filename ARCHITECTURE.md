# HealthCoachAgent 架构详解

> 配套文档：[`PLAN.md`](./PLAN.md)  
> 本文聚焦"为什么这么搭、各模块如何交互"。

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                       Client Layer                                │
│   Web App (Next.js)   微信小程序   Telegram Bot   (RESTful + SSE)  │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                  API Gateway (FastAPI)                            │
│   - REST 路由      - SSE 流式      - 认证       - 限流            │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│              Agent Orchestration (LangGraph)                      │
│   ┌────────────────────────────────────────────────┐              │
│   │             Supervisor（路由决策）               │              │
│   └─────┬────────┬────────┬────────┬────────┬─────┘              │
│         ▼        ▼        ▼        ▼        ▼                    │
│    Nutrition  Fitness  Mental   Analyst   END                    │
│      Coach    Coach    Coach                                     │
│   每个 Coach = 1 个 LangGraph Node                                │
└─────────┬────────┬────────┬────────┬─────────────────────────────┘
          │        │        │        │
┌─────────▼────────▼────────▼────────▼─────────────────────────────┐
│                  MCP Tool Layer（自研）                            │
│  ┌─────────┬─────────┬─────────┬──────────┐                       │
│  │Food-VLM │HealthDB │Scheduler│  Notify  │                       │
│  │  MCP    │  MCP    │  MCP    │   MCP    │                       │
│  └────┬────┴────┬────┴────┬────┴─────┬────┘                       │
└───────┼─────────┼─────────┼──────────┼───────────────────────────┘
        │         │         │          │
┌───────▼────┬────▼────┬────▼─────┬────▼──────┐
│ Qwen3-VL   │Postgres │APScheduler│ Email/    │
│ (API)      │+TSDB    │           │ WeChat/TG │
└────────────┴─────────┴───────────┴───────────┘

┌──────────────────────────────────────────────────────────────────┐
│             Memory Layer（三层记忆）                                │
│   Episodic（事件）   Semantic（画像）   Procedural（习惯）          │
│   Postgres + TSDB    Qdrant 向量库     Postgres                  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│        Cross-cutting：Langfuse 全链路追踪 / 日志 / 配置             │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│             Proactive Engine（主动行为）                            │
│  Triggers：定时 / 阈值 / 事件 → Supervisor.invoke(...)             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据流（典型场景）

### 场景 A：用户拍照吃午饭

```
[Phone Camera]
   │ multipart/form-data
   ▼
POST /api/meal/upload
   │ 文件落盘 + 写 meal_uploads 表
   ▼
触发 Supervisor.invoke({"intent":"meal","image_id":...})
   │
   ▼
Supervisor 路由到 NutritionCoach
   │
   ▼
NutritionCoach
   ├─ 读 Semantic memory（用户过敏/目标/偏好）
   ├─ 调 food_vlm MCP → Qwen3-VL → 结构化结果
   │     {dish:"番茄炒蛋", est_g:300, kcal:280, p:18, c:8, f:18}
   ├─ 写 Episodic memory（这一餐）
   ├─ 调 health_db MCP 查最近 7 天蛋白质摄入
   ├─ LLM 综合 → 生成 Markdown 评估 + 建议
   └─ Command(goto=END, update={"messages":[...]} )
   │
   ▼
SSE 流式返回前端
   │
   ▼
前端渲染：营养表 + 趋势图 + 建议气泡
```

### 场景 B：晚 22:00 主动出日报

```
APScheduler ──cron(22:00)──▶ proactive/jobs.daily_report()
                                  │
                                  ▼
                    Supervisor.invoke({
                       "intent":"daily_report",
                       "user_id": ...,
                       "trigger":"scheduled"
                    })
                                  │
                                  ▼
                    Supervisor 路由 → DataAnalyst
                                  │
              ┌───────────────────┴────────────────────┐
              ▼                                        ▼
         查询全天数据（health_db）              画图（matplotlib）
              │                                        │
              └───────────────────┬────────────────────┘
                                  ▼
                       Supervisor 拿到分析 → 转发 NutritionCoach
                       /FitnessCoach 各写一段建议
                                  │
                                  ▼
                       LangGraph interrupt（HITL）
                       "今天的日报准备好了，发送给您？"
                                  │
                                  ▼ （用户在前端确认）
                       notify MCP → 微信模板消息 / 邮件
```

### 场景 C：阈值触发主动找你

```
Postgres 数据写入触发器（或定时扫描）
   │
   ▼
proactive/triggers.protein_low_streak()
   ├─ 查最近 3 天蛋白摄入
   └─ 全部 < target × 0.7 → fire event
   │
   ▼
Supervisor.invoke({"intent":"alert", "type":"protein_low"})
   │
   ▼
NutritionCoach 起草温柔提醒
   │
   ▼
Mental Coach（自动加入）调整语气，避免压力
   │
   ▼
HITL → 通知用户
```

---

## 3. 关键模块设计

### 3.1 AgentState（状态对象）

```python
# backend/app/agents/state.py
from pydantic import BaseModel
from typing import Literal, Optional

class AgentState(BaseModel):
    user_id: str
    messages: list[dict]                # 完整对话历史
    intent: Literal["chat","meal","activity","daily_report","alert"] = "chat"
    last_user_msg: str = ""
    attached_image: Optional[str] = None
    handoff_to: Optional[str] = None    # 跨 Coach 移交
    awaiting_confirmation: bool = False # HITL 标志
    trace_id: Optional[str] = None      # Langfuse trace
    # 检索/记忆缓存
    user_profile: Optional[dict] = None
    recent_episodic: list[dict] = []
```

LangGraph checkpoint 自动持久化此对象。每次 SSE 流式响应都基于此状态重建上下文。

### 3.2 Supervisor 路由决策

```python
# backend/app/agents/supervisor.py
SUPERVISOR_PROMPT = """你是一名调度员，根据用户意图把请求路由给合适的教练。
教练列表：
- nutrition: 饮食、营养、热量、餐食
- fitness: 训练、运动、动作、伤病恢复
- mental: 情绪、压力、睡眠、焦虑
- analyst: 数据汇总、趋势、对比、报告
- end: 已经回答完毕，可以结束

可以连续路由（如先 analyst 再 nutrition），但每次只输出一个名字。
"""

async def route_decision(state: AgentState) -> str:
    if state.intent == "meal":
        return "nutrition"
    if state.intent == "activity":
        return "fitness"
    if state.intent == "daily_report":
        return "analyst"
    # 通用对话由 LLM 判断
    decision = await llm.ainvoke([
        {"role":"system","content":SUPERVISOR_PROMPT},
        {"role":"user","content":state.last_user_msg}
    ])
    return parse_route(decision)
```

### 3.3 Coach Node 模板

每个 Coach 遵循统一接口：

```python
async def coach_node(state: AgentState) -> Command[Literal["supervisor","__end__"]]:
    # 1. 加载记忆
    profile = await memory.get_semantic(state.user_id)
    history = await memory.get_episodic(state.user_id, days=7)
    
    # 2. 调工具
    tools = await mcp.get_tools(["food_vlm","health_db",...])
    
    # 3. LLM with tools
    response = await llm.bind_tools(tools).ainvoke({...})
    
    # 4. 写 episodic
    await memory.add_episodic(state.user_id, response)
    
    # 5. 决定下一步
    if 需要其他coach: return Command(goto="supervisor", update={"handoff_to":"fitness"})
    return Command(goto="__end__", update={"messages":[response]})
```

### 3.4 三层记忆

| 层 | 内容 | 存储 | 召回方式 | 生命周期 |
|---|---|---|---|---|
| Episodic | 每餐、每次运动、每次对话片段 | Postgres + TSDB | 时间窗 + Filter | 30 天后摘要归档 |
| Semantic | 过敏、目标、伤病、偏好 | Qdrant 向量库 | 语义检索 + 标签 | 永久（用户可删） |
| Procedural | 沟通风格、提醒偏好 | Postgres KV | 直接读 | 持续滚动更新 |

```python
# backend/app/agents/memory.py
class MemoryManager:
    async def add_episodic(self, user_id, event): ...   # INSERT
    async def get_episodic(self, user_id, days=7, kind=None): ...
    async def add_semantic(self, user_id, fact): ...    # 向量化
    async def search_semantic(self, user_id, query, k=5): ...
    async def get_procedural(self, user_id) -> dict: ...
    async def update_procedural(self, user_id, patch): ...
    async def compress_old(self, user_id, days=30): ... # 老 episodic 摘要
```

### 3.5 MCP Server 自研

每个 Server 都是独立 Python 进程，通过 stdio（开发）或 SSE（生产）和 client 通信。

```python
# backend/app/mcp_servers/food_vlm/server.py
from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("food-vlm")

@app.list_tools()
async def list_tools():
    return [Tool(
        name="recognize_food",
        description="识别图像中的食物并估算营养",
        inputSchema={
            "type":"object",
            "properties":{
                "image_b64":{"type":"string"},
                "hint":{"type":"string","description":"用户文字提示"}
            },
            "required":["image_b64"]
        }
    )]

@app.call_tool()
async def call_tool(name, arguments):
    if name == "recognize_food":
        result = await call_qwen_vl(arguments["image_b64"], arguments.get("hint",""))
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

启动方式：
```bash
python -m app.mcp_servers.food_vlm.server   # stdio
python -m app.mcp_servers.food_vlm.server --sse --port 7801  # SSE
```

### 3.6 模型路由层（API 优先 + 本地回退）

```python
# backend/app/llm/router.py
from app.core.config import settings

class ModelRouter:
    def __init__(self):
        self.providers = {
            "main_chat":   [DeepSeekProvider(), ClaudeProvider(), QwenLocalProvider()],
            "vision":      [QwenVLProvider(), GPT5VProvider(), QwenVLLocalProvider()],
            "router":      [DeepSeekProvider(), QwenLocalSmallProvider()],
        }
    
    async def call(self, role: str, **kwargs):
        last_err = None
        for provider in self.providers[role]:
            try:
                return await provider.call(**kwargs)
            except (RateLimitError, APIError, TimeoutError) as e:
                last_err = e
                logger.warning(f"{provider} failed: {e}, trying next")
                continue
        raise RuntimeError(f"All providers failed for {role}: {last_err}")
```

**关键**：每个 provider 实现统一接口 `call(messages, tools, stream, ...)`，对上层透明。

### 3.7 主动行为引擎

```python
# backend/app/proactive/triggers.py

class TriggerBase:
    name: str
    async def check(self, user_id) -> bool: ...
    async def fire(self, user_id): ...

class ScheduledTrigger(TriggerBase):
    """cron 触发，如每晚 22:00 出日报"""

class ThresholdTrigger(TriggerBase):
    """阈值触发，如连续 3 天蛋白不足"""

class EventTrigger(TriggerBase):
    """事件触发，如体重突变 > 1kg/天"""

# proactive/jobs.py 注册到 APScheduler
scheduler.add_job(
    daily_report_for_all_users,
    CronTrigger(hour=22, minute=0),
    id="daily_report"
)
scheduler.add_job(
    threshold_scan,
    IntervalTrigger(minutes=30),
    id="threshold_scan"
)
```

### 3.8 HITL（Human-in-the-Loop）

利用 LangGraph 原生 `interrupt`：

```python
from langgraph.types import interrupt

async def notify_node(state):
    decision = interrupt({  # 中断，等待用户输入
        "type": "confirm_send",
        "preview": state.draft_message
    })
    if decision == "approve":
        await notify_mcp.send(...)
    return state
```

前端通过 SSE 收到 interrupt 事件 → 弹确认框 → POST `/chat/resume` → 后端 `graph.ainvoke(Command(resume=...))`。

---

## 4. 数据库 Schema（核心表）

```sql
-- 用户
users(id, name, email, created_at, ...)

-- 用户画像（Semantic memory 持久层）
user_profiles(
  user_id, goal, allergies[], dislikes[], 
  diseases[], height_cm, weight_kg, target_weight, 
  activity_level, ...
)

-- 餐次（Episodic）
meals(
  id, user_id, ts, image_url,
  dishes JSONB,        -- [{name,grams,kcal,p,c,f}]
  total_kcal, total_p, total_c, total_f,
  source TEXT          -- 'photo' | 'manual'
)
SELECT create_hypertable('meals','ts');

-- 运动（Episodic）
activities(
  id, user_id, ts, type, duration_min,
  intensity, hr_avg, calories_burned, source
)
SELECT create_hypertable('activities','ts');

-- 体征（Episodic）
vitals(user_id, ts, weight_kg, body_fat, hrv, sleep_min, ...)
SELECT create_hypertable('vitals','ts');

-- 对话（Episodic）
conversations(id, user_id, started_at, ended_at)
messages(id, conv_id, role, content, tool_calls JSONB, created_at)

-- 主动通知
notifications(id, user_id, type, draft, status, created_at, sent_at)

-- 评估（开发用）
eval_runs(id, model, prompt_version, score, details JSONB, ts)
```

**安全**：所有 SQL 走 SQLAlchemy 参数化查询，**严禁字符串拼接**（参考工程安全规范 Rule 1）。

---

## 5. 前端架构

### 5.1 技术栈
- **Next.js 15** App Router + RSC
- **AI SDK 5**（Vercel）+ **AI Elements** 组件库
- **shadcn/ui** + Tailwind 4
- **Zustand** 状态管理（轻量）
- **TanStack Query** 数据请求
- **Recharts** 图表
- **lucide-react** 图标

### 5.2 页面结构
```
/                       重定向到 /chat
/chat                   主对话（流式 + Agent 工具调用气泡）
/meal                   拍照上传 + 历史餐次
/activity               运动记录
/dashboard              今日/本周/本月趋势
/inbox                  主动通知中心
/settings/profile       用户画像
/settings/data          数据导出/删除
/settings/integrations  微信/Telegram 接入
```

### 5.3 流式 Agent 渲染（关键）

```tsx
// app/(chat)/page.tsx
import { useChat } from "@ai-sdk/react";
import { Message, ToolCall, Reasoning } from "@vercel/ai-elements";

export default function ChatPage() {
  const { messages, append } = useChat({ api: "/api/chat" });
  return (
    <>
      {messages.map(m => (
        <Message key={m.id} role={m.role}>
          {m.parts.map(p => {
            if (p.type === "text") return <span>{p.text}</span>;
            if (p.type === "tool-invocation") return <ToolCall {...p} />;
            if (p.type === "reasoning") return <Reasoning>{p.text}</Reasoning>;
          })}
        </Message>
      ))}
    </>
  );
}
```

后端 SSE 流式输出 `text`/`tool-invocation`/`reasoning` 三种 part。

---

## 6. 部署形态

### 6.1 开发期（W1-W6）
```
本地开发机
├── docker compose up
│   ├── postgres
│   ├── timescaledb
│   ├── qdrant
│   └── langfuse
├── uvicorn backend
└── pnpm dev frontend

外网访问：cpolar / frp 内网穿透（免费版够用）
```

### 6.2 试用期（W7-W8，5-10 人共用）
```
腾讯云轻量服务器（4 核 8G，¥80/月）
├── docker compose up（pg/qdrant/langfuse/backend）
├── frontend 部署到 Vercel（免费）
└── 域名（可选）.top 6 元/年

数据库每日自动备份到 COS
```

### 6.3 长期（v2）
- 后端搬到 K8s（弹性扩容）
- 微信小程序上架
- 商业化（订阅制）

---

## 7. 可观测性（必须做好）

**全链路 Langfuse**：
- 每个 Supervisor.invoke 创建一个 trace
- 每个 Coach node 一个 span
- 每个工具调用一个 span
- 每次 LLM 调用一个 generation（含 token / 成本 / 延迟）
- 每次记忆读写一个事件

**报警**：
- API 错误率 > 5%（当日累计）→ 邮件
- 单次 trace 成本 > ¥1 → 邮件
- 触发红线词 → 立即邮件

---

## 8. 与已有项目的复用

你已有的 `PalmprintQuality-R1` 中：
- `evaluate_quality_*.py`：质量评估思路可复用到"食物图片质量"判定（模糊/光线差时拒识）
- VLM 调用模式：可直接复用到 `food_vlm` MCP Server
- conda env `visualquality-cuda12`：本地回退时直接用

不直接复用，但思路一致。

---

## 9. 下一步

1. ✅ PLAN.md 已写
2. ✅ 本架构文档
3. ⏭️ ADR 0001-0005（关键决策）
4. ⏭️ README.md
5. ⏭️ 项目Q&A速查.md 追加
6. ⏭️ W1 第一个工单：仓库初始化
