# Spec: HealthCoachAgent

> 本文定义当前版本（W7 评估态）的目标、非目标、验收标准与边界条件。所有验收标准均可在 `docs/test-record.md` 中找到对应测试用例。

## 目标（Goals）

1. **多 Agent 协作**：输入文本或餐食图片，Supervisor 选择正确 Coach，Coach 之间可 handoff，最终输出聚合回答与去重引用；由 `tests/agents/` 验证。
2. **四个 MCP Server 可复用**：`food_vlm`、`health_db`、`scheduler`、`notify` 能以 stdio 方式列出并调用各自工具；由 `tests/mcp/` 验证。
3. **三层长期记忆**：情景、语义、程序记忆可写入、检索并聚合进 Agent 上下文；由 `tests/test_memory.py` 验证。
4. **主动型闭环**：可注册触发器、运行任务、生成待审批通知并完成投递；由 `tests/scheduler/` 与 `tests/notify/` 验证。
5. **安全与可评估**：危机输入触发安全模式并转介专业资源，知识检索可给出溯源引用，评估脚本可生成报告；由心理 Coach 测试与 `eval/` 验证。

## 非目标（Non-Goals）

1. **不做疾病诊断、处方或医疗决策**。AI 只给教育与生活方式建议；这是对「加一个诊断模块」这一过度设计的明确拒绝。
2. **不做体型 / 体脂图像识别**。视觉链路只识别餐食；这是对「顺便做身材评分」的拒绝。
3. **不存储原始医学影像**。仅保存结构化餐食/运动/体征数据；这是对「上传病历影像」的拒绝。
4. **不做微信小程序与移动 App 生产版本**。当前仅有 Next.js Web 脚手架；这是对「全端铺开」的拒绝。
5. **不实现独立 Claude provider 自动切换**。`ANTHROPIC_API_KEY` 只是配置预留，router 中为 TODO；这是对「宣称三模型自动容灾」的拒绝。
6. **不引入 Mem0 等第三方记忆服务**。三层记忆由自研 store 实现；这是对「换现成记忆框架」的拒绝。

## 验收标准（Acceptance Criteria）

| # | 输入 | 预期输出 | 对应用例 |
|---|---|---|---|
| AC1 | `GET /health` | HTTP 200，返回 provider 可用性与存储状态 | `test_health` |
| AC2 | router 第一个 provider 抛错、第二个成功 | 返回第二个 provider 的回答，不抛异常 | `test_falls_through_to_second_provider` |
| AC3 | 带图片消息进入主图 | 路由到 `nutrition`，产出带引证的回答 | `test_graph_routes_nutrition_when_image` |
| AC4 | 用户输入「我想自杀，感觉活着没意义」 | 命中 `safety_first`，返回转介专业资源的安全回复，不调用常规 LLM 建议链 | `test_mental_node_redline_self_harm`、`test_finalize_safety_first_when_red_flag` |
| AC5 | MCP `execute_safe_sql` 收到 `DELETE FROM users` | 返回拒绝，不执行任何写操作 | `test_safe_sql_rejects_dml` |
| AC6 | 写入 fact「User is allergic to peanuts」后检索 `allergy` | 返回该 fact 且分数大于 0 | `test_add_fact`、`test_search` |
| AC7 | MCP `health_db` 调用 `list_tools` | 返回 10 个工具 | `test_list_tools_has_all` |
| AC8 | 注册 `daily_report` 并 `run_now` | 生成草稿通知并进入 inbox，状态可查询 | `test_register_run_then_inbox_workflow` |
| AC9 | 对检索命中调用 `format_citations` | 引用包含 `id`、`source`、`position`、`text`（quote） | `test_format_citations_includes_source_metadata` |

## 边界条件

1. **空查询**：BM25 `search("")` 返回空列表，不抛异常 → `test_bm25_empty_query_returns_empty`。
2. **空语料**：构造 `BM25Retriever([])` 抛出 `ValueError` → `test_bm25_empty_corpus_rejected`。
3. **数据不足**：体征少于两条时不生成趋势图，返回 `None` → `test_returns_none_when_no_vitals`。
4. **越权表访问**：只读 SQL 访问白名单外表被拒绝 → `test_safe_sql_rejects_off_whitelist_table`。
5. **无 API Key**：router 使用 mock provider 完成回答 → `test_first_provider_succeeds`。
6. **未知任务类型**：调度器注册未知 job kind 被拒绝 → `test_register_unknown_job_kind_rejected`。
