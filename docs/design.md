# Design: HealthCoachAgent

## 1. 架构总览与数据流

```
[餐食图片 / 文本 / 体征]
        │
        ▼
FastAPI: /chat · /chat/stream · /api/proactive/*
        │
        ▼
AgentState ──► supervisor_node（启发式 + LLM tie-breaker + loop guard）
        │
        ├─► nutrition_coach_node ─┐
        ├─► fitness_coach_node   ─┤
        ├─► mental_coach_node    ─┤
        └─► data_analyst_node    ─┘
                 │
        handoff / self-handoff 阻止
                 ▼
        finalize_node（聚合 + 引用去重 + safety_first）
                 ▼
[CoachAnswer: answer, citations, visited_coaches, handoff]
        │
        ├── MCP: food_vlm（VLM 识别） / health_db（结构化数据 + 只读 SQL）
        ├── Memory: episodic(SQLite) + semantic(Qdrant) + procedural(KV)
        ├── RAG: BM25 检索三套知识语料 → 4 条引证
        └── Proactive: TriggerEngine → JobExecutor → NotificationService（HITL）
```

存储：默认 SQLite（`data/healthcoach.db`）+ 嵌入式 Qdrant（`data/qdrant/`）；Docker 可选方案见 `docker-compose.optional.yml` 与 `ADR/0006`。

## 2. 切片策略

- **切片单位**：一条 `Document` 即一个可检索片段（食物条目、原则、训练建议、危机处置条目）。
- **chunk 结构**：`{ id, source, position, text, tags, metadata }`。`id` 全局唯一，`source` 为公开资料出处，`position` 为语料内序号（引用中回传，便于溯源），`text` 为完整片段；`tags` 用于过滤，`metadata` 保留扩展字段。
- **切片数量**：营养、健身、心理三套语料合计约 30+ 条，由 `build_*_corpus()` 构建，无外部向量化步骤。
- **可追溯性**：`format_citations()` 输出 `{ id, source, position, tags, score, quote }`，Coach 回答必须携带该列表。

## 3. 检索逻辑

```
search(query, k=4, tag_filter=None, exclude_tags=None, min_score=None) → list[Hit]

1. _tokenize：中文 jieba.cut_for_search，英文小写切词，混合文本分别处理
2. BM25Okapi.get_scores 计算相关度
3. tag_filter / exclude_tags 过滤（危机场景用于排除 redline 语料）
4. min_score 可选阈值（默认不加，短语料 IDF 可能为 0）
5. 按分数降序取 TopK
```

空查询直接返回 `[]`；空语料在构造时抛 `ValueError`。实现：`backend/app/rag/retriever.py`。

## 4. Prompt 模板

```
系统指令：你是健康教练，只基于给定资料与用户数据给出一般性建议，不做诊断、不开处方。
上下文：检索到的 TopK 引用 + 三层记忆（情景事件 / 语义事实 / 程序偏好）
用户问题：user_message
输出要求：中文；结构化建议；必须列出引用；无法确认时说明不确定性；命中红线时走固定安全回复。
```

## 5. 拒答规则

触发条件：

1. 自伤 / 自杀 / 严重抑郁 / 惊恐发作等关键词命中 `_REDLINE_KW`、`_SEVERE_DEPRESSION_KW` 或 `_PANIC_KW`。
2. 用户要求诊断、处方或替代医生决策（由系统指令与红线约束）。
3. 涉及体型 / 体脂图像评分或原始医学影像存储（非目标，功能不存在）。

拒答回复（固定文案示例，实际按危机类型选择）：

```
【危机干预】如果您有自伤或自杀意念，请立即拨打：
中国24小时心理援助热线 400-161-9995（北京心理危机干预热线）。
同时，请尽快告知一位您信任的亲友或家人，并前往最近的医院急诊心理科。
您的安全是第一优先级。请不要独自承受，帮助随时可用。
（如果您正处于紧急危险中，请立即拨打 120 或前往急诊。）
```

命中后不调用常规 LLM 建议链，输出模式置为 `safety_first`。对应测试见 `test-record.md`「拒答测试」。

## 6. 接口适配与输入校验

| 接口 / 函数 | 输入 | 校验 | 核心逻辑 / 边界 | 对应测试 |
|---|---|---|---|---|
| `create_app()` / `GET /health` | 环境变量 | Settings 读 `.env` | 启动 scheduler 与通知服务；失败时降级跳过 | `test_root`、`test_health` |
| `LLMRouter.chat()/stream()` | role + messages | 角色必须配置 provider | 逐个尝试，失败自动切下一个；全失败抛 `ProviderError` | `test_first_provider_succeeds` 等 6 项 |
| `build_main_graph()` / `supervisor_node()` | `AgentState` | 图片/文本关键字与 LLM 输出校验 | 选 Coach、loop guard、handoff | `test_graph_routes_nutrition_when_image` 等 8 项 |
| `finalize_node()` | 多个 `CoachAnswer` | 引用字段合法性 | 聚合、引用去重、安全优先 | `test_finalize_*` 系列 |
| `nutrition_coach_node()` | 图片 + message + user_id | VLM 输出 schema 校验 | 识别 → 画像 → 7 天聚合 → 记忆 → RAG → LLM | `test_graph_routes_nutrition_when_image` |
| `fitness_coach_node()` | 文本 + user_id | 风险词优先 | 训练知识 RAG、安全优先、handoff | `test_fitness_coach_node_returns_answer` 等 9 项 |
| `mental_coach_node()` / `_detect_redline()` | 文本 + user_id | 正则红线检测 | 命中即固定安全回复；否则 RAG + LLM | `test_detect_redline`、`test_mental_node_redline_self_harm` 等 |
| `data_analyst_node()` | 文本 + user_id | 数据条数阈值 | 查询聚合 + matplotlib 图表；数据不足返回 None | `test_data_analyst_node_returns_command` 等 14 项 |
| `BM25Retriever.search()` | query + k/filter | 空语料构造即报错、空查询返回空 | 分词、打分、过滤、TopK | `test_bm25_*` 系列 8 项 |
| `format_citations()` | `list[Hit]` | 依赖 Hit 结构 | 输出可序列化引用（含 position） | `test_format_citations_includes_source_metadata` |
| `EpisodicStore.add_event()/query_*()` | user_id + 事件/时间范围 | 空表返回空列表 | SQLite 读写与聚合 | `test_add_unstructured_event`、`test_query_meals_empty` 等 |
| `SemanticStore.add_fact()/search()` | user_id + fact/query | 用户过滤、confidence 过滤 | Qdrant upsert / query_points；不可用降级 | `test_add_fact`、`test_search` 等 |
| `ProceduralStore.set_key()/get_key()` | user_id + key/value | key 不存在返回 None | KV 偏好与反馈学习 | `test_set_and_get_key`、`test_learn_from_feedback_brief` 等 |
| `FoodRecognizer.recognize()` | 图片路径/data URL/HTTP URL | schema 校验负数等非法值 | 真实 VLM；无 Key 回退 mock；解析失败抛错 | `test_mock_recognizer_default`、`test_recognizer_falls_back_to_mock_when_no_key` 等 12 项 |
| 四个 MCP `build_server().list_tools()/call_tool()` | 工具名 + 参数 | 未知工具/缺参返回错误 | stdio 协议封装 | `test_list_tools`、`test_call_tool_*` 等 21 项 |
| `SchedulerCore.build_trigger()/register/run_now()` | cron/interval + job kind | 二者互斥、job kind 白名单 | APScheduler 注册、立即执行、取消 | `test_build_trigger_*`、`test_register_then_run_now_creates_draft` 等 |
| `validate_sql()/execute_safe_select()` | SQL 字符串 | 仅 SELECT、表白名单、LIMIT | 注入拒绝、参数化执行 | `test_validate_accepts_safe`、`test_validate_rejects_unsafe` 等 |
| `dispatch_pending()` / NotificationService | 通知记录 | channel 可用性检查 | file/console/db 投递与状态统计 | `test_dispatch_pending_via_mcp`、`test_channels_and_dispatcher` 等 |
| `eval/run_eval.py` | `cases.jsonl` + `--limit/--no-judge` | 用例 ID 与断言字段 | 跑主图 → 断言 → judge → 生成报告 | 抽样运行，见 `eval/eval_report.md`（非 pytest 用例） |

> 设计边界：`eval/run_eval.py` 为人工运行的评估工具，不纳入 pytest 覆盖；其余上表接口均有对应测试组。
