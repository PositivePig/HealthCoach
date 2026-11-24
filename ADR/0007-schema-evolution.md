# ADR 0007 - Schema 演进策略：metadata.create_all 的局限与 db-reset 临时方案

- **日期**：2026-05-18（W2 D4 实战发现）
- **状态**：Accepted（W2 阶段）；W4 切换到 Alembic

## 背景

W2 D4 闭环 demo 第一次运行时，遇到：

```
sqlite3.OperationalError: table notifications has no column named channel
```

原因：W2 D3 已经通过 `Base.metadata.create_all(...)` 创建了 `notifications` 表（旧 schema 无 `channel` 列）。W2 D4 在 ORM 模型上加了 `channel / delivery_attempts / delivery_error` 三列，但 `create_all` **不会修改已存在表**（只会创建缺失表）。

## 决策

W2 阶段（dev profile）采取最小成本方案：

1. **现在**：开发阶段一旦改了表结构，运行 `bash scripts/dev.sh db-reset` 清空 SQLite 重新建表
2. **W4**：切换到 Alembic 迁移管理（生产前必做）

## 触发条件 → 行动

| 你做了什么 | 必须做什么 |
|---|---|
| 加了新列 / 改了列类型 / 加索引 | `db-reset` 重建 |
| 加了新表 | 自动生效（create_all 会建） |
| 删表 / 删列 | `db-reset` 重建 |
| 仅改 ORM 业务方法（无 DDL） | 无需操作 |

## 为何不立刻上 Alembic

- W2 重点是 MCP server 本身的协议、工具设计、HITL，不是 DDL
- Alembic 在 async + 多 backend（sqlite/postgres）下有些样板代码，会拖慢节奏
- 当前 dev DB 内的数据可随时丢弃
- 从 W4 开始，记忆系统会持续累积有价值的真实数据，那时再上 Alembic 才有意义

## 必须 W4 切 Alembic 的硬指标

- DB 中存有需要保留的真实用户数据
- 计划部署给朋友试用（W7-W8）
- 切到 Postgres（生产前提）

## 落地（W4）

```bash
# 初始化
uv run alembic init backend/app/db/migrations

# 自动生成第一份基线迁移
uv run alembic revision --autogenerate -m "baseline"

# 之后每次改 ORM 模型：
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

ADR 也会同步更新到 W4 状态。

## 预防

W3+ 我会在 PLAN.md 的"每周收尾 checklist"里加一条：
- [ ] 本周改过 ORM 模型？→ 已 db-reset 并重新跑 demo？

这样不会有"上一天的数据库 schema 把今天的 demo 卡死"的尴尬。
