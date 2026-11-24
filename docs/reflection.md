# Reflection — HealthCoachAgent

## 今天最大的认知变化

把 README 从「W1 planning / 107 tests」改成作品集版本时，我发现**文档和代码会各自漂移**。AI 最初按旧 README 建议保留「Next.js 15 / AI SDK 5 / shadcn/ui / Claude 自动切换」的写法，但我打开 `frontend/package.json` 看到的是 Next.js 16.2.6 与 AI SDK 6，打开 `backend/app/llm/router.py:129` 只看到 `Anthropic (TODO)`。我选择以代码为准重写技术栈，并把「Claude 自动切换」「微信小程序」放进已知限制，而不是继续沿用旧文案。

这件事改变了我对「完成度」的判断：作品集的价值不在于写了多少功能，而在于读者能否按 README 跑通并验证我声称的东西。于是我给 README 的每条能力都找了对应测试或 demo 命令，AC1–AC9 都能在 `docs/test-record.md` 里找到用例编号。

## 今天最困难的地方

卡在 `uv run pytest -q` 上：190 个用例全部报 `FileNotFoundError: '/tmp'`。原因是 `tests/conftest.py:32` 硬编码了 Linux 路径，而我在 Windows 上运行。AI 建议换成 `os.environ["TEMP"]`，我没有直接采纳——系统临时目录里可能有别的项目的 `.env`，测试隔离仍不可靠。改用 pytest 的 `tmp_path` fixture 后，190 个用例一次通过。

修完又冒出 1 个失败：`test_search` 断言 `0 == 1`。这次 AI 建议把生产代码的 `query_points` 改回旧 `client.search` 去迁就测试，我拒绝了：qdrant-client 新版 API 就是 `query_points`，错的是测试。把 mock 目标从 `fastembed.TextEmbedding` 改成 `backend.app.memory.semantic.TextEmbedding`、把返回值改成 `query_points` 的 `QueryResponse.points` 结构后通过。这个过程让我确认一个原则：**当测试与实现冲突时，先判断谁代表真实行为，而不是选改动更小的那一侧**。

## 如果再学一遍

我会在写 README 之前先跑一次 `uv run pytest --collect-only -q` 和一次全量测试，并且把「声称的能力 → 证据文件/用例」做成表格再动笔。这样就不会出现「 README 写 107 tests、实际 191 collected」的落差，也不会到交付前才发现测试在 Windows 上根本跑不起来。

我也会更早建立 `docs/spec.md` 的非目标清单。这次正是因为有「不做 Claude provider / 不做小程序」的非目标，我才有依据拒绝 AI 把临时 API 和夸大描述塞进作品集的建议——非目标不只是限制范围，它还是做判断时的锚点。
