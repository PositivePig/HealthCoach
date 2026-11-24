# ADR 0003 - 自研 MCP Server，不用现成集成

- **日期**：2026-05-18
- **状态**：Accepted

## 背景

工具调用层有多种实现方式：
1. LangChain Tool（直接 Python 函数装饰）
2. OpenAI Function Calling（厂商专属）
3. **MCP（Model Context Protocol）**——Anthropic 推动，2026 年事实标准

本项目把 4 个能力（Food-VLM / HealthDB / Scheduler / Notify）做成独立 MCP Server。

## 决策

**全部能力以 MCP Server 形式实现**，并在 LangGraph 中通过 MCP client 调用。

## 为什么是 MCP

| 维度 | LangChain Tool | OpenAI FC | MCP |
|---|---|---|---|
| 跨厂商通用 | ✅ | ❌ | ✅ |
| 进程隔离 | ❌ | ❌ | ✅ |
| 可被 Claude Desktop / Cursor 复用 | ❌ | ❌ | ✅ |
| 标准化协议 | ❌ | ⚠️ | ✅ |
| 学习价值 | 中 | 低 | **高（事实标准）** |
| 简历加分 | 低 | 低 | **高** |

## 自研而非用现成 MCP Server 的原因

GitHub 上已有 `mcp-server-postgres`、`mcp-server-filesystem` 等。本项目仍自研：

1. **学习价值**：自己写一遍才能彻底理解协议（tool/resource/prompt 三大原语、stdio/SSE 双传输、能力协商、错误模型）
2. **业务定制**：HealthDB 不是通用 SQL，要做权限隔离、字段级脱敏
3. **多服务编排经验**：4 个 server 并行启动、健康检查、生命周期管理是工程难点
4. **可开源**：写完 push GitHub，是简历项目

## 设计原则

### 单一职责
| Server | 唯一职责 |
|---|---|
| `food_vlm` | 仅做"图像 → 食物结构化结果" |
| `health_db` | 仅做"健康数据 CRUD + 安全 SQL" |
| `scheduler` | 仅做"注册 / 取消 / 列出定时任务" |
| `notify` | 仅做"投递消息到不同通道" |

### 工具粒度
- ❌ 不要做"超级工具"（一个 tool 干 10 件事）
- ✅ 每个工具职责清晰、参数 schema 严格

### 协议选择
- 开发期：**stdio**（本地启动方便）
- 生产期：**SSE**（独立部署、可水平扩展）
- 配置切换：环境变量 `MCP_TRANSPORT=stdio|sse`

### 安全
- `health_db.execute_sql` 工具：**强制白名单**（只允许 SELECT + 受限表）
- 所有写操作走单独工具（如 `add_meal`），不暴露通用 INSERT
- 严禁 SQL 字符串拼接（参考工程安全规范 Rule 1，全部用参数化）

## MCP Server 启动管理

```yaml
# docker-compose.yml 片段（生产 SSE 模式）
food-vlm-mcp:
  build: ./backend
  command: python -m app.mcp_servers.food_vlm.server --sse --port 7801
  environment: [DASHSCOPE_API_KEY]

health-db-mcp:
  build: ./backend
  command: python -m app.mcp_servers.health_db.server --sse --port 7802
  depends_on: [postgres]
```

```python
# backend/app/mcp_servers/client.py
class MCPClientPool:
    """统一管理多个 MCP server 的连接"""
    async def connect_all(self): ...
    async def get_tools(self, names: list[str]) -> list[BaseTool]: ...
```

## 后果

### 优点
- ✅ 工具能力被复用：Claude Desktop / Cursor / 任何 MCP client 都能用本项目的 server
- ✅ 进程隔离：某个 server 崩了不影响主 Agent
- ✅ 学习深度：把协议吃透
- ✅ 可独立 push 开源（4 个 server 各一个仓库）

### 缺点
- ⚠️ 启动复杂度：需 docker compose 编排
- ⚠️ 调试比直调函数麻烦：靠 Langfuse + MCP inspector

## 落地动作

- W2 全周用于 MCP Server 开发，每天一个
- 用 [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) 单独验证
- W2 周末用 Claude Desktop 接入测试，证明"通用性"

## 风险

| 风险 | 缓解 |
|---|---|
| MCP SDK 版本变动 | 锁定版本 |
| 性能开销（IPC） | 高频小任务直接函数调用，工具粒度的才走 MCP |
