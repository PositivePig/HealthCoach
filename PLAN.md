# HealthCoachAgent 项目计划书

> 一个主动型多模态健康教练 Agent  
> 立项日期：2026-05-18  
> 预计周期：8 周（W1~W8）  
> 目标可用度：D2 个人助手级（自己每天真用、5-10 个朋友家人能用）

---

## 0. TL;DR

- **做什么**：用户拍照吃饭/记录运动/戴手环 → 4 个 AI 教练（营养/健身/心理/数据）协作 → 给出评估、建议、长期跟踪、主动提醒
- **核心差异**：**主动型** + **多 Agent 协作** + **跨会话长期记忆** + **可解释**
- **技术栈**：FastAPI + LangGraph + MCP + Next.js 15 + Postgres + Qdrant + Langfuse
- **模型策略**：**API 优先**（DeepSeek-V3.2 + Qwen3-VL + Claude），失败/隐私敏感时回退本地
- **预算**：每月 ¥20-100（API 调用）+ 0 硬件投入
- **最终入口**：Web App（主） + 微信小程序（W7-W8） + Telegram Bot（彩蛋）

---

## 1. 产品定位

### 1.1 一句话定义
> 一位 7×24 在你身边、懂你、会主动找你的 AI 健康教练团队。

### 1.2 用户画像
- **P0（首要用户）**：项目作者本人，需求是减脂/增肌/睡眠/工作压力管理
- **P1（朋友圈试用）**：3-10 位关心健康但记录懒的朋友
- **P2（潜在用户）**：上班族、有健身/控糖/孕期等长期健康目标的人群

### 1.3 与现有产品差异

| 对比对象 | 它们的不足 | HealthCoach 的差异 |
|---|---|---|
| Keep / 薄荷健康 | 模板化、被动等待用户记录 | **主动型 Agent**，会推送、会追问 |
| ChatGPT / 文心一言 | 无记忆、无数据、每次重新开始 | **跨会话长期记忆** + 真实数据 |
| MyFitnessPal | 单纯记录工具 | **多 Agent 协作 + 推理** |
| 单 LLM 健康助手 | 单一视角、易幻觉 | **多 Coach + RAG 引证** |

### 1.4 不做什么（红线）
- ❌ 疾病诊断 / 处方建议（仅做"建议就医"提示）
- ❌ 严重情绪干预（自伤倾向直接转专业资源）
- ❌ 体型/体脂图像识别（隐私 + 准确率风险）
- ❌ 存储原始医学影像

---

## 2. 核心功能（按优先级）

### P0 必做（W1-W6）
1. **拍照识别食物 + 营养估算**：上传照片 → VLM 识别 → 估算热量/蛋白/碳水/脂肪 → 写入数据库
2. **多 Coach 协作对话**：用户提问 → Supervisor 路由 → 1~N 个 Coach 协作 → 流式回复
3. **三层长期记忆**：Episodic（每餐/运动）+ Semantic（用户画像）+ Procedural（沟通风格）
4. **数据看板**：今日/本周/本月营养、运动、睡眠趋势图
5. **每日/每周自动报告**：APScheduler 定时触发 → 数据 Agent 汇总 → 推送
6. **主动提醒**：阈值触发（连续 3 天蛋白不足）+ 事件触发（体重突变）

### P1 强烈推荐（W6-W7）
7. **运动记录与建议**：手动输入或 HealthKit/米家同步 → 教练评估 + 下次计划
8. **HITL 中断与确认**：Agent 推送计划/重要建议前必须用户确认
9. **微信小程序入口**：核心功能搬上小程序，订阅消息推送

### P2 加分项（W8 / v2）
10. **语音输入**（识别后入流）
11. **Telegram Bot**（彩蛋）
12. **导出周报为 PDF**
13. **手环数据自动同步**（米家 / Apple HealthKit MCP）

---

## 3. 技术架构（详见 ARCHITECTURE.md）

```
Next.js 15 前端
    │ SSE / WebSocket
FastAPI Gateway（流式 + HITL）
    │
LangGraph Supervisor
    ├─ Nutrition Coach
    ├─ Fitness Coach
    ├─ Mental Coach
    └─ Data Analyst
    │
MCP Tool Layer（自研 4 个 Server）
    ├─ Food-VLM MCP
    ├─ HealthDB MCP
    ├─ Scheduler MCP
    └─ Notify MCP
    │
存储层：Postgres + TimescaleDB + Qdrant + Mem0
观测层：Langfuse 全链路追踪
```

---

## 4. 技术选型（详见 ADR/）

| 组件 | 选型 | 关键理由 |
|---|---|---|
| Agent 编排 | **LangGraph** | 状态机式、可中断、可观测、checkpoint 强 |
| 工具协议 | **MCP** | 2026 事实标准，简历价值高，自研 server 学透协议 |
| 主对话模型 | **DeepSeek-V3.2 (API)** | 国内便宜大碗，关键场景升级 Claude |
| 视觉模型 | **Qwen3-VL-Plus (API)** | 中文菜识别强 |
| 路由/分类 | **DeepSeek-V3.2 / 本地 Qwen3-4B** | 高频低成本 |
| Embedding | **bge-m3 (本地)** | 免费、效果好、支持中英 |
| 后端 | FastAPI + uvicorn + SSE | 流式 Agent 标配 |
| 前端 | Next.js 15 + AI SDK 5 + Vercel AI Elements | 流式 UI 一把梭 |
| 数据库 | Postgres + TimescaleDB | 关系数据 + 时序数据一锅端 |
| 向量库 | Qdrant | 工业级、过滤强 |
| 记忆框架 | Mem0 + 自建分层 | 标准库 + 自研深度 |
| 调度 | APScheduler | Python 生态最成熟 |
| 观测 | Langfuse（自部署） | 开源、免费、Agent 调试必备 |
| 包管理 | uv | 比 pip 快 10-100 倍 |
| 容器 | docker compose | 一键起所有依赖 |

### 4.x 模型调用策略（**API 优先 + 本地回退**）

```python
# 配置层级
MODEL_ROUTING = {
    "main_chat":   ["deepseek-v3.2", "claude-sonnet-4.5", "qwen3-14b-local"],
    "vision":      ["qwen3-vl-plus", "gpt-5v", "qwen3-vl-7b-local"],
    "router":      ["deepseek-v3.2", "qwen3-4b-local"],
    "embedding":   ["bge-m3-local"],   # 本地直接做，省钱
}
# 故障时按列表顺序自动 fallback
```

详见 `ADR/0001-model-strategy.md`。

---

## 5. 项目目录结构

```
HealthCoachAgent/
├── README.md
├── PLAN.md                     # 本文件
├── ARCHITECTURE.md
├── ADR/
│   ├── 0001-model-strategy.md
│   ├── 0002-langgraph-vs-pydantic-ai.md
│   ├── 0003-mcp-self-hosted.md
│   ├── 0004-memory-design.md
│   └── 0005-proactive-engine.md
├── docker-compose.yml
├── pyproject.toml              # uv
├── .env.example
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── chat.py
│   │   │   ├── meal.py
│   │   │   ├── activity.py
│   │   │   ├── reports.py
│   │   │   └── webhook.py      # 微信/Telegram 入口
│   │   ├── agents/
│   │   │   ├── supervisor.py
│   │   │   ├── state.py
│   │   │   ├── memory.py
│   │   │   ├── prompts/
│   │   │   └── nodes/
│   │   │       ├── nutrition_coach.py
│   │   │       ├── fitness_coach.py
│   │   │       ├── mental_coach.py
│   │   │       └── data_analyst.py
│   │   ├── mcp_servers/
│   │   │   ├── food_vlm/
│   │   │   ├── health_db/
│   │   │   ├── scheduler/
│   │   │   └── notify/
│   │   ├── proactive/
│   │   │   ├── triggers.py
│   │   │   └── jobs.py
│   │   ├── llm/
│   │   │   ├── router.py       # 模型路由 + fallback
│   │   │   └── providers/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── migrations/     # Alembic
│   │   ├── eval/
│   │   │   ├── dataset.json
│   │   │   ├── trajectory.py
│   │   │   └── judge.py
│   │   └── core/
│   │       ├── config.py
│   │       ├── logging.py
│   │       └── langfuse.py
│   ├── tests/
│   └── scripts/
│
├── frontend/                   # Next.js 15 (App Router)
│   ├── app/
│   │   ├── (chat)/page.tsx
│   │   ├── meal/page.tsx
│   │   ├── activity/page.tsx
│   │   ├── dashboard/page.tsx
│   │   └── api/
│   ├── components/
│   ├── lib/
│   └── package.json
│
├── miniprogram/                # 微信小程序（W7-W8）
│
└── docs/
    ├── architecture.md
    ├── mcp-servers.md
    ├── agent-flows.md
    ├── eval-report.md
    └── deployment.md
```

---

## 6. 8 周里程碑（按周 + 按天）

> 原则：每周至少出一个**可见、可验证**的产物，不出就反思调整。

### 📍 W1（5/18-5/24）：地基

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | 仓库初始化、`pyproject.toml`、`docker-compose.yml`（postgres/qdrant/langfuse） | `docker compose up` 全绿 |
| D3 | 模型路由层 `llm/router.py` + API key 配好 + Mock 测试 | 调一句话回正常 |
| D4 | FastAPI 骨架 + `/health` + `/chat`（SSE 单 LLM） | curl 看到流式输出 |
| D5 | Langfuse 接通 | 能在 UI 看到 trace |
| D6-7 | 第一个 LangGraph 单节点 hello-world Agent | trace 里看到节点 |

**W1 产出**：能跑的 FastAPI + LangGraph hello world，全链路有 trace。

### 📍 W2（5/25-5/31）：MCP Server 自研

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | `food_vlm` MCP Server（接 Qwen3-VL API） | claude desktop 测试调用成功 |
| D3 | `health_db` MCP Server（Postgres CRUD） | 可写入/查询餐次 |
| D4 | `scheduler` MCP Server（APScheduler 包装） | 可注册定时任务 |
| D5 | `notify` MCP Server（先做控制台 mock，后期接微信） | 能触发 |
| D6-7 | LangGraph 通过 MCP client 调用 4 个 server | 一个 Agent 能用全部工具 |

**W2 产出**：4 个 MCP Server 全部跑通，单 Agent 能用全部工具。

### 📍 W3（6/1-6/7）：营养 + 健身 Coach

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | `nodes/nutrition_coach.py` + 营养库 RAG（USDA + 中国食物成分表） | 拍张照→营养表 |
| D3-4 | `nodes/fitness_coach.py` + 训练动作库 RAG | 问"卧推怎么练"有引证 |
| D5 | `supervisor.py` 路由逻辑 | 用户问题正确分发 |
| D6-7 | Coach 间 handoff（练完→营养） | 跨 Coach 协作流跑通 |

**W3 产出**：拍张照+问问题，2 个 Coach 协作给出建议，全程 Langfuse 可见。

### 📍 W4（6/8-6/14）：心理 Coach + 数据分析师 + 三层记忆

| 日 | 任务 | 验收 |
|---|---|---|
| D1 | `mental_coach.py`（含红线检测） | 触发关键词时正确转介 |
| D2 | `data_analyst.py`（SQL 沙箱 + 画图工具） | 能查"最近 7 天蛋白摄入" |
| D3-4 | Episodic 记忆（餐次/运动/对话） | 能跨会话回忆 |
| D5 | Semantic 记忆（用户画像，含过敏/目标） | 注册时填，写入向量库 |
| D6 | Procedural 记忆（沟通风格学习） | 多轮后语气稳定 |
| D7 | 记忆压缩（>30 天滚动摘要） | 老数据自动归档 |

**W4 产出**：4 Coach 全到位，三层记忆生效，能跨会话记住"我对花生过敏"。

### 📍 W5（6/15-6/21）：主动型 Agent + 调度

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | `proactive/triggers.py`（阈值/事件/定时三类触发器） | 单测全过 |
| D3 | 定时任务：每晚 22:00 出日报 | 22:00 真出 |
| D4 | 阈值触发：连续 3 天蛋白质<目标 → 主动消息 | 模拟数据触发 |
| D5 | HITL：主动推送前需用户确认（LangGraph interrupt） | 中断/恢复跑通 |
| D6-7 | 通知通道（先邮件 / 控制台 / 后期微信模板消息） | 能收到 |

**W5 产出**：Agent 真的会"主动找你"，并且推送前会等你确认。

### 📍 W6（6/22-6/28）：前端 Next.js

| 日 | 任务 | 验收 |
|---|---|---|
| D1 | Next.js 15 项目 + AI SDK 5 + Vercel AI Elements | 起服务 |
| D2-3 | 聊天页（流式 SSE + 工具调用渲染） | 流式回答 + 看到 Agent 调用工具 |
| D4 | 拍照上传页（手机相册 + 摄像头） | 真机拍照能传 |
| D5 | 数据看板（recharts 趋势图） | 三张图：营养/运动/睡眠 |
| D6 | 推送中心（消息列表 + 已读/未读） | UI 顺畅 |
| D7 | 移动端样式调优 | iPhone Safari 体验 OK |

**W6 产出**：你拿手机就能用了。

### 📍 W7（6/29-7/5）：评估 + 调优 + 微信小程序（可选）

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | 自建 100 题评估集（营养/健身/心理/数据各 25） | json 文件 |
| D3 | LLM-as-judge（打分模板 + 引证检查） | 自动跑出分数 |
| D4 | Trajectory 评估（工具调用合理性） | 报告产出 |
| D5-6 | 根据评估结果调 prompt / 路由 / RAG | 第二轮跑分提升 |
| D7 | （可选）微信小程序骨架 + 拍照 + 聊天 | 手机扫码能用 |

**W7 产出**：一份评估报告 `eval-report.md` + 调优后的版本。

### 📍 W8（7/6-7/12）：文档 + Demo + 收尾

| 日 | 任务 | 验收 |
|---|---|---|
| D1-2 | README + 部署文档 + 架构图 | 别人能照着跑起来 |
| D3 | Telegram Bot 彩蛋（webhook） | 1 天搞定 |
| D4 | Demo 视频（3-5 分钟） | 录屏成片 |
| D5 | 邀请 3-5 位朋友试用 + 收集反馈 | 反馈表 |
| D6-7 | 回归 bug + v2 路线图（含 RL Agent） | 收尾 |

**W8 产出**：能给别人看、能给别人用、有反馈、有 v2 计划。

---

## 7. 风险登记

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | 食物识别误差大 | 中 | 估算偏差 | HITL 修正 + 多图融合 + 用户校准 |
| R2 | 用户记录懒（3 天弃疗） | **高** | 数据稀疏 | 主动推送 + 简化输入 + 语音 + 微信门槛低 |
| R3 | LLM 幻觉给错医学建议 | 中 | 误导用户 | RAG 必须引证 + 红线词检测 + 免责声明 |
| R4 | 隐私担忧 | 中 | 不敢用 | 本地化部署 + 加密 + 可导出/删除 + 不上传医学影像 |
| R5 | API 成本失控 | 低 | 烧钱 | 预算告警 + 缓存 + 路由小模型 + 本地兜底 |
| R6 | 1-2 月做不完 | 中 | 烂尾 | 严控里程碑、P2 可砍、每周必出可见产物 |
| R7 | API 限流/不稳 | 中 | 用户体验差 | 多 provider fallback（已设计） |
| R8 | LangGraph 学习曲线 | 中 | 进度慢 | W1 先做单节点 hello world，循序渐进 |

---

## 8. 评估方案

### 8.1 评估集
- **来源**：自建 100 题
  - 营养类 25 题：含拍照题（10）+ 文本问答（15）
  - 健身类 25 题
  - 心理类 25 题（含红线场景 5 题）
  - 数据类 25 题（SQL 推理）
- **格式**：JSON，每题含 question / image / expected_traits / red_lines

### 8.2 评估维度
| 维度 | 方法 | 目标 |
|---|---|---|
| 答案质量 | LLM-as-judge（GPT-5 当裁判） | ≥4.0/5.0 |
| 引证准确率 | 检查 RAG 引用文档真实存在 | ≥95% |
| 工具调用合理性 | Trajectory 评估 | ≥90% 合理 |
| 红线触发率 | 红线题必须正确处理 | 100% |
| 跨会话记忆准确率 | 设计 10 个跨会话题 | ≥90% |
| 响应延迟 | 首 token / 完整回答 | <1s / <10s |

### 8.3 回归测试
- 每次 prompt/模型/工具大改后跑全量评估
- 结果存档 `docs/eval-report.md`

---

## 9. 安全与合规

- ✅ API Key 走 `.env` + 环境变量，禁止硬编码
- ✅ 用户健康数据加密存储（Postgres pgcrypto）
- ✅ 数据库参数化查询（防 SQL 注入，参考工程安全规范）
- ✅ Mental Coach 红线词检测（自伤/严重抑郁 → 转专业资源）
- ✅ 所有医学建议附"非诊断、建议就医"免责声明
- ✅ 用户可一键导出/删除全部数据
- ❌ 不存原始医学影像
- ❌ 不做疾病诊断

---

## 10. 成本预算

### 10.1 时间预算
- 8 周 × 每周约 15-25 小时 = **120-200 小时**

### 10.2 金钱预算
| 项 | 月费 | 备注 |
|---|---|---|
| API（DeepSeek + Qwen-VL + Claude 关键场景） | ¥20-100 | 自用 |
| 服务器（开发期本地，后期可选轻量云） | ¥0-30 | cpolar 内网穿透免费 |
| 域名（可选） | ¥6/年 | .top 域名 |
| **合计** | **¥20-130/月** | |

### 10.3 硬件
- ✅ **0 元起步**：现有开发机够用
- 可选：手环 ¥200 / 体脂秤 ¥100（v2 再说）

---

## 11. 第一周可执行 Checklist（W1）

> 复制到 GitHub Issue 或 todo，逐条勾选

- [ ] 创建 Git 仓库 `HealthCoachAgent`，建 `develop` 分支
- [ ] `uv init`，写 `pyproject.toml`（fastapi、langgraph、langchain、mcp、langfuse、qdrant-client、psycopg、pydantic-settings）
- [ ] 写 `docker-compose.yml`：postgres + timescaledb 扩展 + qdrant + langfuse
- [ ] `docker compose up -d` 全部跑起来
- [ ] `.env.example`：DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ANTHROPIC_API_KEY / LANGFUSE_*
- [ ] 实现 `app/llm/router.py`：支持 deepseek/qwen-vl/claude，按列表 fallback
- [ ] 写测试：故意把第一个 provider 设为坏 key，验证自动切到下一个
- [ ] FastAPI `app/main.py` + `/health` + 一个 SSE `/chat` demo
- [ ] 接入 Langfuse SDK，调用一次 LLM 并在 UI 看到 trace
- [ ] LangGraph 单节点 hello-world：echo state.input 加上 LLM 改写
- [ ] README 写"本地启动 5 步"
- [ ] Push 到远端，截一张 Langfuse trace 截图存 `docs/`

---

## 12. 立即下一步

1. **本计划书写完后**：开 W1 第一个工单，初始化仓库 + docker-compose
2. **本周末**：W1 全部跑通，下周一开始写 MCP Server
3. **每周日**：写一篇周记 → 追加到 `项目Q&A速查.md`，反思 + 调整下周

---

> 计划是死的，人是活的。每周回看一次，发现走偏立即调。  
> 如果某周发现 P0 做不完，先砍 P2 → 再砍 P1，**绝不延期里程碑**。
