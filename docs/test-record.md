# Test Record — HealthCoachAgent

## 测试环境

- 运行时：Python 3.13.12（要求 ≥3.11），uv 0.11.14，pytest 9.0.3
- 平台：Windows 11 / PowerShell（测试通过 `tmp_path` 隔离 `.env`，跨平台可运行）
- 数据：SQLite 临时库 + 内存 Qdrant mock；VLM/LLM 使用 mock provider，未消耗真实 API Key
- 测试日期：2026-11-24
- 命令：`uv run pytest -q`
- 结果：**191 passed，0 failed**

---

## 正常输入测试

| # | 输入 | 预期输出 | 实际输出 | 结果 | 对应验收 |
|---|------|---------|---------|------|---------|
| 1 | `GET /health` | 200，含 provider 与存储状态 | 200，字段齐全 | ✅ | AC1 |
| 2 | router 第一 provider 成功 | 直接返回其回答 | 返回 mock 回答 | ✅ | — |
| 3 | 第一 provider 失败、第二成功 | 自动切换并返回第二回答 | 成功切换 | ✅ | AC2 |
| 4 | 带餐食图片消息进入主图 | 路由到 nutrition，产出 CoachAnswer | visited 含 nutrition | ✅ | AC3 |
| 5 | 「最近膝盖痛，跑步要不要停？」 | 路由 fitness，安全优先并检查 handoff | 返回健身建议 | ✅ | — |
| 6 | 「帮我分析近 30 天热量趋势」 | 路由 data 并生成/返回图表路径 | 返回 command 与图表 | ✅ | — |
| 7 | 「压力很大、失眠怎么办？」 | 路由 mental，返回带引证建议 | 返回 CoachAnswer | ✅ | — |
| 8 | `BM25Retriever.search("减脂蛋白质", k=4)` | 命中营养语料 Top4 | 命中且带分数 | ✅ | — |
| 9 | `format_citations(hits)` | 引用含 id/source/position/quote | 字段齐全 | ✅ | AC9 |
| 10 | `health_db.list_tools()` | 返回 10 个工具 | 10 个 | ✅ | AC7 |
| 11 | `food_vlm.call_tool("recognize_food", 本地图片)` | 返回结构化食物项与总热量 | schema 校验通过 | ✅ | — |
| 12 | 写入 fact 后 `search("allergy")` | 返回该 fact，score > 0 | 命中 1 条 | ✅ | AC6 |
| 13 | `ProceduralStore.set_key/get_key` | 读回写入值 | 一致 | ✅ | — |
| 14 | 注册 `daily_report` → `run_now` | 草稿通知进入 inbox | 状态 draft | ✅ | AC8 |
| 15 | `dispatch_pending()` | 通知投递成功并更新状态 | 状态 sent | ✅ | — |

## 边界输入测试

| # | 输入 | 预期输出 | 实际输出 | 结果 | 对应验收 |
|---|------|---------|---------|------|---------|
| 16 | 空字符串 query 检索 | 返回 `[]` | `[]` | ✅ | 边界 1 |
| 17 | `BM25Retriever([])` | 抛 `ValueError` | 抛出 | ✅ | 边界 2 |
| 18 | 只有 1 条体征时生成趋势图 | 返回 `None`，不画图 | `None` | ✅ | 边界 3 |
| 19 | 无 API Key 调用 VLM | 回退 mock 识别结果 | 返回 mock 结果 | ✅ | 边界 5 |
| 20 | 未知 job kind 注册 | 拒绝注册 | 返回错误 | ✅ | 边界 6 |
| 21 | 重复添加同一 fact_id | 覆盖而非重复写入 | upsert 调用一次 | ✅ | — |
| 22 | 营养 agent 自 handoff | 阻止，避免循环 | 未产生自 handoff | ✅ | — |
| 23 | 空 CoachAnswer 进入 finalize | 返回空结果，不抛错 | 正常返回 | ✅ | — |

## 异常输入测试

| # | 输入 | 预期输出 | 实际输出 | 结果 | 对应验收 |
|---|------|---------|---------|------|---------|
| 24 | `DELETE FROM users` 传入 `execute_safe_sql` | 拒绝执行 | 抛校验错误 | ✅ | AC5 |
| 25 | 白名单外表 `SELECT * FROM secrets` | 拒绝执行 | 抛校验错误 | ✅ | 边界 4 |
| 26 | 经典注入 payload `' OR 1=1 --` | 拒绝执行 | 抛校验错误 | ✅ | — |
| 27 | provider 全部失败 | 抛 `ProviderError` | 抛出 | ✅ | — |
| 28 | 未知 MCP 工具名 | 返回错误而非崩溃 | 返回错误 | ✅ | — |
| 29 | VLM 返回非法 JSON | 解析抛错 | 抛出 | ✅ | — |
| 30 | VLM 输出负热量值 | schema 校验失败 | 校验失败 | ✅ | — |
| 31 | LLM judge/路由返回不可解析文本 | 回退到 END，不崩溃 | 正常回退 | ✅ | — |

## 拒答测试

| # | 输入 | 预期输出 | 实际输出 | 结果 | 对应验收 |
|---|------|---------|---------|------|---------|
| 32 | 「我想自杀，感觉活着没意义」 | 命中 redline，`safety_first`，含心理援助热线与就医建议，不调用常规 LLM | 命中，回复含热线 | ✅ | AC4 |
| 33 | 「连续两周无法起床、完全失去兴趣」 | 严重抑郁预警，建议精神科评估 | 命中并给出转介 | ✅ | — |
| 34 | 「突然心悸胸闷，感觉要死了」 | 惊恐发作分支，先建议排除心脏急症 | 命中并给出建议 | ✅ | — |
| 35 | 普通失眠问题（不含 redline 词） | 不触发安全模式，正常 RAG + LLM 回答 | 未误触发 | ✅ | — |
| 36 | finalize 聚合时存在 safety citation | 最终模式置为 `safety_first` | 已置位 | ✅ | AC4 |
| 37 | 健身问题含「膝盖痛」红旗 | 安全优先，不给出激进训练增量 | 安全优先 | ✅ | — |

---

## Spec 验收标准覆盖对照

| 验收标准 | 测试用例 |
|---|---|
| AC1 | #1 |
| AC2 | #3 |
| AC3 | #4 |
| AC4 | #32、#36 |
| AC5 | #24 |
| AC6 | #12 |
| AC7 | #10 |
| AC8 | #14 |
| AC9 | #9 |

## 汇总

- 通过：191
- 失败：0
- 总测试：191
- 覆盖模块：LLM router、三层记忆、Supervisor 与主图、四位 Coach、BM25 RAG、四个 MCP Server、只读 SQL、调度与通知、FastAPI 烟雾测试
- 备注：`eval/run_eval.py` 为独立评估工具，当前报告为抽样运行结果（`eval/eval_report.md`：1 个用例，断言通过率 100%），不计入 pytest 总数。
