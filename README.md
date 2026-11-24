# HealthCoachAgent

> 主动型多模态健康教练 Agent：拍照上传 → 4 位 AI 教练协作评估 → 长期记忆跟踪 → 主动提醒。

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-191%20passed-brightgreen)]()
[![Stage](https://img.shields.io/badge/stage-W7%20%2F%20evaluated-orange)]()
[![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20LangGraph%20%7C%20MCP-purple)]()

---

## 项目描述

这是一个面向个人作品集展示的 Agent 工程实践项目。它不是单 LLM 套壳：后端用 LangGraph 编排一个 Supervisor 和四位领域 Coach（营养 / 健身 / 心理 / 数据），并通过自研 MCP Server 接入视觉识别、健康数据库、定时调度和通知投递。系统具备三层长期记忆与主动触发能力，能够在没有用户提问时按规则生成提醒并走人工审批（HITL）。

项目当前实现到 W7（评估与调优），后端能力完整、测试覆盖充分；前端以可用聊天页为主，其余页面作为可继续迭代的脚手架。**README 中对能力边界的描述与代码现状一致**，未完成项统一放在「已知限制」中。

---

## 功能特性

- **多 Agent 协作**：`supervisor` 启发式路由 + LLM tie-breaker，支持 Coach 间双向 handoff、loop guard 与结果聚合（含引用去重）。
- **多模态营养评估**：Qwen-VL 识别餐食图片 → 结构化食物项 → 用户画像 + 近 7 天聚合 + BM25 知识检索（4 条引证）→ LLM 综合建议。
- **四位领域 Coach**：营养、健身、心理、数据；心理 Coach 内置危机红线检测，命中即安全回复并转介专业资源。
- **四个自研 MCP Server**：`food_vlm`（1 个工具）、`health_db`（10 个）、`scheduler`（8 个）、`notify`（5 个），支持 stdio，可被 Claude Desktop / MCP Inspector 复用。
- **三层长期记忆**：情景记忆（SQLite）、语义记忆（Qdrant + fastembed）、程序记忆（偏好 KV），统一聚合进 Agent prompt。
- **主动型引擎**：定时 / 阈值 / 事件触发器，任务执行、待审批通知与多渠道投递，提供 HTTP API。
- **可观测性与评估**：Langfuse 埋点（可选）；`eval/run_eval.py` 支持断言检查、LLM judge 与引证准确率报告。
- **模型容错**：DeepSeek / DashScope 按角色路由，provider 失败自动切换，无 Key 时 mock 回退，便于离线开发与测试。

---

## 架构速览

```
        图片 / 文本
             │
      FastAPI (/chat, /chat/stream)
             │
     ┌───────▼────────┐
     │   Supervisor    │  启发式 + LLM 路由 / loop guard / handoff
     └───────┬────────┘
   ┌─────────┼─────────┬─────────┐
   ▼         ▼         ▼         ▼
Nutrition  Fitness   Mental     Data      ← BM25 RAG + 三层记忆 + LLM
   │         │         │         │
   └─────────┴────┬────┴─────────┘
                  ▼
        finalize（聚合 + 引用去重）
                  │
      MCP: food_vlm / health_db / scheduler / notify
                  │
      SQLite · 嵌入式 Qdrant · Langfuse（可选）
```

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · LangGraph · MCP · APScheduler · SQLAlchemy/aiosqlite · Qdrant · rank-bm25/jieba · Langfuse |
| 模型 | DeepSeek-V3（对话）· Qwen-VL-Plus（视觉）· fastembed bge-small（嵌入）；Claude 为可选扩展点，尚未接入 |
| 前端 | Next.js 16.2.6 · React 19.2.4 · AI SDK 6 · TypeScript · Tailwind CSS 4 · Recharts |
| 工程 | uv · pytest · ruff · `scripts/dev.sh` · docker compose（可选） |

---

## 安装与环境要求

**必需**

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
- 至少一个 LLM API Key：`DEEPSEEK_API_KEY` 或 `DASHSCOPE_API_KEY`
- 用于运行 `scripts/dev.sh` 的 Bash 环境；Windows 可用 Git Bash

**可选**

- Docker + Docker Compose（只有需要 Postgres / Qdrant Server / 自部署 Langfuse 时）
- Node.js ≥ 20（仅前端）
- 无 Docker 时默认使用 SQLite + 嵌入式 Qdrant，见 `ADR/0006`

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY
uv sync
```

---

## 运行

```bash
# 可选：需要容器化依赖时使用（注意 compose 文件名带 .optional）
bash scripts/dev.sh up
# docker compose -f docker-compose.optional.yml up -d

# 测试
bash scripts/dev.sh test

# 启动后端：http://localhost:8000，Swagger 在 /docs
bash scripts/dev.sh run

# 另开终端做烟雾测试（/health + /chat + SSE）
bash scripts/dev.sh smoke
```

前端（可选）：

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000/chat 已接通后端 SSE；其余页面为脚手架
```

### 主要接口

| 路径 | 用途 |
|---|---|
| `GET /` | 服务信息与版本 |
| `GET /health` | 健康检查、provider 可用性与存储状态 |
| `GET /docs` | Swagger UI |
| `POST /chat` | 非流式聊天（hello graph） |
| `GET /chat/stream?message=...` | SSE 流式聊天 |
| `GET/POST/DELETE /api/proactive/triggers` | 触发器管理 |
| `GET /api/proactive/hitl/pending` · `POST /api/proactive/hitl/approve` | 通知审批 |
| `POST /api/proactive/notify` · `POST /api/proactive/triggers/{id}/run` | 主动发送与手动触发 |

### 演示命令

```bash
# 食物识别（mock，无需 Key）
bash scripts/dev.sh mcp-smoke

# 食物识别（真实 Qwen-VL）
bash scripts/dev.sh mcp-smoke-real data/test_images/meal.jpg

# Supervisor + Nutrition Coach + RAG
bash scripts/dev.sh demo-supervisor data/test_images/food.jpeg "我目标减脂，这餐够吗？" jason

# 健身 ⇄ 营养双向 handoff
bash scripts/dev.sh demo-dual-handoff

# 心理红线与安全回复
bash scripts/dev.sh demo-mental-scenarios

# 主动闭环：注册任务 → 立即运行 → HITL 审批 → 投递
bash scripts/dev.sh demo-w2-loop

# 评估（断言 + LLM judge）
uv run python eval/run_eval.py --no-judge --limit 10
```

---

## 测试

```bash
uv run pytest -q
# 当前结果：191 passed
```

测试覆盖：LLM router 回退、三层记忆、Supervisor 路由与 handoff、四位 Coach、BM25 检索、四个 MCP Server、只读 SQL 注入防御、调度与通知、FastAPI 烟雾测试。详细用例与执行结果见 [`docs/test-record.md`](./docs/test-record.md)。

---

## 项目结构

```
HealthCoachAgent/
├── backend/app/            # FastAPI、Agent、MCP Server、memory、proactive、RAG、DB
│   ├── main.py             # 应用入口（version 0.1.0-w7）
│   ├── agents/             # supervisor / main_graph / nodes（四位 Coach）
│   ├── mcp_servers/        # food_vlm / health_db / scheduler / notify
│   ├── memory/             # episodic / semantic / procedural
│   ├── proactive/          # triggers / jobs / notifications
│   ├── llm/                # router 与 provider
│   ├── rag/                # BM25 retriever 与三套知识语料
│   └── db/                 # SQLAlchemy 模型、repository、safe_sql
├── frontend/               # Next.js 前端（聊天页可用，其余为脚手架）
├── tests/                  # pytest 测试套件（191 个用例）
├── eval/                   # 评估用例、脚本与报告
├── scripts/                # dev.sh 与端到端 demo 脚本
├── data/                   # 本地 SQLite、嵌入式 Qdrant、测试图片（运行产物）
├── docs/
│   ├── spec.md             # 目标、非目标、验收标准、边界条件
│   ├── design.md           # 架构、数据流、接口与拒答规则
│   ├── test-record.md      # 测试用例与执行结果
│   ├── ai-log.md           # AI 协作记录与人工判断
│   ├── reflection.md       # 个人复盘
│   ├── agent-graph.md      # 多 Agent 图说明
│   ├── mcp-*.md            # 四个 MCP Server 接入文档
│   ├── W7-COMPLETE.md      # W7 阶段完成报告
│   └── w7-eval-report.md   # W7 评估记录
├── ADR/                    # 7 篇架构决策记录
├── ARCHITECTURE.md         # 架构详解
├── PLAN.md                 # 8 周开发计划
├── pyproject.toml          # 依赖与工具配置
└── README.md               # 本文件
```

---

## 文档导航

| 文档 | 内容 |
|---|---|
| [`docs/spec.md`](./docs/spec.md) | 目标 / 非目标 / 验收标准 / 边界条件 |
| [`docs/design.md`](./docs/design.md) | 数据流、接口设计与拒答规则 |
| [`docs/test-record.md`](./docs/test-record.md) | 正常 / 边界 / 异常 / 拒答测试记录 |
| [`docs/ai-log.md`](./docs/ai-log.md) | AI 协作与人工判断 |
| [`docs/reflection.md`](./docs/reflection.md) | 复盘与认知变化 |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 架构详解、数据流、模块设计 |
| [`PLAN.md`](./PLAN.md) | 8 周计划与里程碑 |
| [`ADR/`](./ADR/) | 模型策略、LangGraph、MCP、记忆、主动引擎等 7 篇决策记录 |
| [`docs/agent-graph.md`](./docs/agent-graph.md) | 主图与 Supervisor 设计 |
| `docs/mcp-*.md` | 四个 MCP Server 接入说明 |
| [`eval/eval_report.md`](./eval/eval_report.md) | 评估报告（当前为抽样运行结果） |

---

## 已知限制

为保证作品集描述可信，以下能力**尚未完成或未实现**：

- 前端只有 `/chat` 接通后端 SSE；`/meal` 调用的 `/meal/upload` 端点后端尚未实现，`/dashboard`、`/activity`、`/notifications` 为占位页。
- `/chat` 与 `/chat/stream` 使用最小 hello graph；四位 Coach 的完整链路通过 `scripts/demo-*.py` 与主图 API 展示，未直接挂在 `/chat` 路由上。
- Claude/Anthropic 在 router 中是预留扩展点（TODO），未实现独立 provider；技术栈不等于已完成自动三模型切换。
- `Mem0`、Alembic 迁移脚本、微信小程序均不在当前代码中；`pyproject.toml` 中的 alembic 仅为依赖占位。
- Langfuse 默认关闭；需在 `.env` 填 keys 并将 `LANGFUSE_ENABLED` 设为 `true`。
- 语义记忆在 Qdrant 不可用时降级为空结果，不影响主流程但会缺失语义层上下文。
- 食物营养数值来自公开资料的近似值，仅用于教育与演示，不构成医疗建议。

---

## 红线（不做的事）

- 疾病诊断 / 处方
- 严重情绪危机的人工干预（命中红线时转介专业资源）
- 体型 / 体脂图像识别
- 存储原始医学影像

---

## License

项目作为个人作品集展示，暂未指定开源许可证；如需复用代码请联系作者。
