# ADR 0006 - 无 Docker 开发模式（SQLite + Qdrant embedded + Langfuse Cloud）

- **日期**：2026-05-18
- **状态**：Accepted（W2~W7 默认采用，W8 视部署需要切换）

## 背景

经环境探查，开发机为 **K8s pod 内的容器**（`/proc/1/cgroup` 显示 `kubepods/burstable/...`，`/.dockerenv` 存在），无法在容器内再起 docker daemon（无 `--privileged`、无 systemd、cgroup v1 受限）。

强行装 docker（DinD / podman rootless）大概率失败或不稳，会消耗 1-2 天的非核心调试时间，与"重原理重新技术"的项目目标冲突。

## 决策

W2~W7 默认采用"无 Docker 开发模式"：

| 组件 | 原方案（docker） | 当前方案（无 docker） | 影响 |
|---|---|---|---|
| Postgres + TimescaleDB | docker compose | **SQLite**（标准库）+ SQLAlchemy 抽象 | 损失 hypertable / 持续聚合特性；普通时间索引足以 |
| Qdrant 向量库 | docker compose | **Qdrant 内嵌**（`qdrant-client[fastembed]` 本地模式） | 几乎无影响 |
| Langfuse 观测 | docker compose 自部署 | **Langfuse Cloud**（jp.cloud.langfuse.com） | 反而更省心，免费额度 50k events/月 |
| 后端运行 | docker | uv + uvicorn 直接跑 | 无差异 |

W8（部署给 5-10 个朋友试用）时再考虑切回 docker：
- 选项 1：腾讯云轻量服务器（¥30-100/月，原生 Linux + docker）
- 选项 2：保持 SQLite + Qdrant 嵌入式，单机直接跑（简单场景够用）

## 落地

### 1. 配置层
`backend/app/core/config.py` 增加：
```python
storage_backend: Literal["sqlite", "postgres"] = "sqlite"
sqlite_path: str = "./data/healthcoach.db"
langfuse_base_url: str = ""          # 兼容用户提供的命名
@property def db_url -> sqlite+aiosqlite:// 或 postgresql+asyncpg://
@property def langfuse_resolved_host -> base_url 或 host
```

### 2. 数据层（W2 起）
- 用 SQLAlchemy 2.0 + async：`from sqlalchemy.ext.asyncio import create_async_engine`
- 模型定义无关存储后端：表结构在 SQLite 和 Postgres 上一致（少数特殊 type 用 sqlalchemy `JSON`）
- 时序数据：`meals` / `activities` / `vitals` 用普通索引 `(user_id, ts DESC)` 即可，不用 hypertable

### 3. 向量层（W4 起）
```python
from qdrant_client import AsyncQdrantClient
# 嵌入式：path 指向本地目录
client = AsyncQdrantClient(path="./data/qdrant")
# W8 部署时：改成 url="http://qdrant:6333" 即可
```

### 4. 观测层（W1 已通）
Langfuse Cloud 已在 W1 配通：
- `https://jp.cloud.langfuse.com`
- `start_as_current_observation(name=..., as_type="generation")` 包裹每次 LLM 调用
- 启动 lifespan 自动 `flush_langfuse()` 退出前清缓冲

### 5. 旧 docker-compose 保留
`docker-compose.yml` 重命名为 `docker-compose.optional.yml`，W8 部署时复用。

## 后果

### 优点
- ✅ 立即可用，不浪费时间在环境上
- ✅ 学习重点（多 Agent / MCP / 长期记忆 / 主动型）完全不受影响
- ✅ Langfuse Cloud 比自部署省事，trace 可分享给协作者
- ✅ SQLAlchemy 抽象保证未来切回 Postgres 改一行配置即可

### 缺点
- ⚠️ 失去 TimescaleDB 高级特性（短期不需要）
- ⚠️ Qdrant 嵌入式不能与多进程共享（单进程开发够用）
- ⚠️ Langfuse Cloud 数据走出口（自部署更隐私，但开发期可接受）

## 验证

W1 已端到端验证：
- DeepSeek API 真实调用 ✅
- LangGraph 单节点 ✅
- FastAPI SSE 流式（37 token 事件）✅
- Langfuse Cloud trace 上报 ✅
- pytest 9/9 通过 ✅
