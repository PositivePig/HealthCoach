# AI Log — HealthCoachAgent

> 每条记录包含目的 / 输入 / 建议 / 人工判断 / 验证五个字段。「人工判断」写明采纳、修改或拒绝了什么及理由；「验证」可在 `docs/spec.md` 与 `docs/test-record.md` 中找到证据。

---

## 第 1 条：2026-11-24 16:05 — README 状态与能力边界重写

| 字段 | 内容 |
|---|---|
| **目的** | 把过时 README（W1 planning / W3 进行中 / 107 tests）改成可用于个人作品集的准确说明。 |
| **输入** | 原 README、`backend/app/main.py`（version 0.1.0-w7）、`frontend/package.json`（Next.js 16.2.6 / AI SDK 6）、`tests/` 清单、`eval/` 报告。 |
| **建议** | AI 建议保留原「8 周里程碑」表格并宣称 Next.js 15 / AI SDK 5、shadcn/ui 与 Claude 自动切换。 |
| **人工判断** | **修改并部分拒绝**：里程碑表改为「已知限制 + 能力边界」；版本号以 `package.json` 为准改成 16.2.6 / AI SDK 6；删除 shadcn/ui 与「Claude 自动切换」宣称（代码里只有配置键和 TODO），因为 spec 非目标已明确不做独立 Claude provider。 |
| **验证** | `README.md` 技术栈表与 `frontend/package.json` 一致；`docs/spec.md` 非目标 5 明确该限制；`docs/test-record.md` 无相关虚假用例。 |

---

## 第 2 条：2026-11-24 16:15 — 测试在 Windows 上全部报错的修复

| 字段 | 内容 |
|---|---|
| **目的** | 全量测试 190 errors，定位并修复，使作品集可复现。 |
| **输入** | `uv run pytest -q` 的完整错误栈，指向 `tests/conftest.py:32` 的 `monkeypatch.chdir("/tmp")`。 |
| **建议** | AI 建议把 `"/tmp"` 改成 `os.environ["TEMP"]`，并继续保留清 `.env` 的逻辑。 |
| **人工判断** | **修改后采纳**：改用 pytest 内置 `tmp_path` fixture（每个测试独立空目录），而不是系统 TEMP——系统 TEMP 可能残留其他项目的 `.env`，隔离不可靠。清 keys、清缓存的逻辑采纳。 |
| **验证** | 修复后 `uv run pytest -q`：190 passed（后续新增引用测试后为 191 passed），见 `docs/test-record.md` 汇总。 |

---

## 第 3 条：2026-11-24 16:22 — 语义记忆搜索测试与实现不一致

| 字段 | 内容 |
|---|---|
| **目的** | 修复唯一失败用例 `TestSemanticStore::test_search`（assert 0 == 1）。 |
| **输入** | `backend/app/memory/semantic.py:266-327` 使用 `query_points` 与 `TextEmbedding.embed`；测试 mock 的是 `fastembed.TextEmbedding` 与 `client.search`。 |
| **建议** | AI 建议把生产代码 `query_points` 改回旧版 `client.search`，以适配现有测试。 |
| **人工判断** | **拒绝该建议，改为修测试**：qdrant-client 新版 API 就是 `query_points`，生产代码正确；测试 mock 目标必须跟随实现。同时把另外两处无效 mock 路径一并改为 `backend.app.memory.semantic.TextEmbedding`，避免真实下载模型。 |
| **验证** | `test_add_fact`、`test_add_fact_with_existing_id`、`test_search` 全部通过，汇总 191 passed；`docs/design.md` 接口表记录该接口。 |

---

## 第 4 条：2026-11-24 16:35 — 六文件框架与引用溯源补齐

| 字段 | 内容 |
|---|---|
| **目的** | 按交付标准补齐 `docs/spec.md`、`design.md`、`test-record.md`、`ai-log.md`、`reflection.md`，并让 RAG 引用满足溯源字段要求。 |
| **输入** | 交付标准、design 模板、`backend/app/rag/retriever.py`、`tests/rag/test_retriever.py`、现有 7 篇 docs。 |
| **建议** | AI 建议在 design 文档中写 chunk 结构 `{id, source, position, text}` 即可，不必改代码。 |
| **人工判断** | **修改后采纳**：文档按该结构写，但同时在 `Document` 增加 `position` 字段并让 `format_citations()` 回传，否则文档与代码不一致；并新增 `test_format_citations_includes_source_metadata` 证明可追溯，写进 design 接口表与 test-record。 |
| **验证** | `docs/spec.md` AC9 ↔ `docs/test-record.md` #9 ↔ 新增测试；`uv run pytest -q` 191 passed。 |

---

## 第 5 条：2026-11-24 16:45 — 前端能力表述与发布前清理

| 字段 | 内容 |
|---|---|
| **目的** | 避免作品集夸大：前端 `/meal` 调用不存在的 `/meal/upload`，其余页面为占位。 |
| **输入** | `frontend/app/meal/page.tsx`、`dashboard/activity/notifications` 页面、`backend/app/main.py` 路由表、`scripts/dev.sh`、`.gitignore`。 |
| **建议** | AI 建议顺手实现 `/meal/upload` 和三个占位 API，让前端全部可用。 |
| **人工判断** | **拒绝**：这些端点不在当前交付范围，临时补 API 会引入未测试代码；改为在 README「已知限制」逐条说明，并把页面状态写清楚。采纳 AI 关于清理重复 `mcp-inspect-db` 分支和忽略本地 DB / eval 产物的建议；**修改**其「忽略 uv.lock」建议为提交锁文件，以保证依赖可复现。 |
| **验证** | `README.md` 已知限制段与代码路由一致；`scripts/dev.sh` 仅剩一个 `mcp-inspect-db`；`.gitignore` 不再忽略 `uv.lock`，新增 `data/*.db` 等规则。 |
