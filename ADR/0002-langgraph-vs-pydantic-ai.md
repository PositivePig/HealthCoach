# ADR 0002 - Agent 编排框架选 LangGraph

- **日期**：2026-05-18
- **状态**：Accepted

## 背景

Agent 编排框架候选：
1. LangGraph（LangChain 团队新框架，状态机）
2. Pydantic AI（轻量，类型安全）
3. CrewAI（多 Agent 角色扮演）
4. AutoGen（微软）
5. 自己撸（不依赖框架）

本项目核心特征：
- **多 Agent 协作**（Supervisor + 4 Coach）
- **跨会话长程对话**（必须 checkpoint）
- **HITL**（必须能中断恢复）
- **流式输出**（SSE）
- **可观测性**（Langfuse 集成）

## 决策

选 **LangGraph**。

## 各候选对比

| 维度 | LangGraph | Pydantic AI | CrewAI | AutoGen | 自撸 |
|---|---|---|---|---|---|
| 多 Agent | ✅ 一等公民 | ⚠️ 需手写 | ✅ 但僵化 | ✅ | ✅ |
| Checkpoint | ✅ 内置 Postgres/Redis | ❌ | ❌ | ⚠️ | 自己写 |
| HITL（interrupt） | ✅ 原生 | ❌ | ❌ | ⚠️ | 自己写 |
| 流式 | ✅ | ✅ | ⚠️ | ✅ | 自己写 |
| Langfuse 集成 | ✅ 一行接入 | ✅ | ⚠️ | ⚠️ | 自己写 |
| 学习曲线 | 中 | 低 | 低 | 高 | 高 |
| 调试体验 | ✅ LangGraph Studio | ⚠️ | 差 | 差 | 自己 |
| 社区活跃度 | ★★★★★ | ★★★★ | ★★★ | ★★★ | — |
| 简历价值 | 高 | 中 | 低 | 中 | 高 |

## 决策依据

1. **HITL 是本项目必须功能**（主动推送前要用户确认）→ LangGraph 的 `interrupt` 是杀手锏
2. **Checkpoint 必须**（跨会话记忆 + 长程任务）→ LangGraph 内置 Postgres checkpointer
3. **多 Agent 标准方案**（Supervisor 模式）→ LangGraph 官方教程一比一对应
4. **LangGraph Studio 调试**：可视化看 state 流转，对新手极友好
5. **Langfuse 集成成熟**：观测性立省一周

## 不选其他的原因

- **Pydantic AI**：极简优雅，但多 Agent + checkpoint 都要自己造，1-2 月内造不完
- **CrewAI**：角色扮演太"魔法"，不利于学习底层
- **AutoGen**：API 复杂、调试痛苦，社区不如 LangGraph
- **自撸**：作为一个"学技术深度"的项目可以，但 8 周内做不到生产级，会被工程细节拖死

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| LangGraph API 变化频繁 | 锁定版本（pyproject 固定 `>=0.2.x,<0.3`） |
| 状态对象设计不当导致难调 | W1 单节点先跑通 + Langfuse trace 辅助 |
| 多 Agent 死循环 | Supervisor 内置 step counter，>10 步强制 END |

## 落地动作

- W1：单节点 hello-world Agent（验证 checkpoint + Langfuse）
- W2：MCP Tool 接入 LangGraph
- W3：Supervisor + 2 Coach
- W4：4 Coach 全到位
- W5：interrupt + 主动行为

## 备选保留

如未来 LangGraph 不再合适，可以迁移到 Pydantic AI（接口相似），核心业务在 `nodes/` 下，迁移成本可控。
