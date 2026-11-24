# Agent Graph (W3+)

> 多 Coach Supervisor 架构。当前 W3 D1：Supervisor + Nutrition Coach（含 RAG）。

---

## 总图

```
                ┌─────────────┐
                │   START     │
                └──────┬──────┘
                       ▼
                ┌─────────────────────────────────┐
                │    supervisor_node              │
                │  - heuristic（关键词/图片）      │
                │  - LLM tie-breaker（router 角色）│
                │  - loop guard（≤2 coaches）     │
                │  - explicit handoff             │
                └────┬─────┬─────┬─────┬──────────┘
                     │     │     │     │
                     ▼     ▼     ▼     ▼
              nutrition fitness  data  finalize
                  │       │       │
                  └───────┴───────┘
                       ▲   ▲
                       │   │ Command(goto="supervisor")
                       │
              （每次 coach 结束都回 supervisor）

   finalize → END
```

## AgentState（关键字段）

| 字段 | 类型 | 用途 |
|---|---|---|
| `user_id` | str | 数据隔离 + 画像加载 |
| `user_message` | str | 当前轮用户输入 |
| `image_path` | str? | 拍照场景 |
| `next_coach` | enum | supervisor 决定 |
| `handoff_to` | str? | coach 主动请求其他 coach 接力 |
| `visited_coaches` | list（带 reducer） | 防回路 |
| `coach_answers` | list[CoachAnswer]（带 reducer） | 累积每位 coach 的回答 |
| `final_answer` / `final_citations` | str / list | finalize 节点合并产出 |

`Annotated[list, operator.add]` 让多次 update 自动 concat（LangGraph 习惯用法）。

## Supervisor 决策流

```
1) 显式 handoff（coach 设了 state.handoff_to 且未访问过）→ 直跳
2) loop guard（visited >= 2）→ finalize
3) heuristic：
     image_path 存在 → nutrition
     '运动/训练/跑步' 词命中 → fitness
     '本周/趋势/平均' 词命中 → data
     '吃/餐/营养/热量/蛋白' 词命中 → nutrition
   只在最高分 ≥ 次高分+1 时确认（防歧义）
4) 模糊 → router 角色 LLM 决策（cheap：deepseek-chat 8 token）
5) 已访问的目标 → 替换为下一个未访问 / end
```

## Nutrition Coach 内部流程

```
state ──┐
        ▼
  食物识别 (FoodRecognizer，复用 W2D1)
        │
        ▼
  用户画像 + 近 7 天聚合 (W2D2 health_db)
        │
        ▼
  RAG 检索 (BM25, top-4)
        │   query = user_msg + goal + identified_foods
        ▼
  LLM synthesize
        │   system: 营养师 prompt
        │   user: profile + stats + food + refs + question
        ▼
  解析 HANDOFF: fitness 后缀（model 自决） / heuristic（"刚跑/练完"）
        ▼
  emit CoachAnswer + visited=['nutrition'] + handoff_to=?
```

## RAG 选型（W3 阶段）

| 维度 | 选择 | 理由 |
|---|---|---|
| 语义层 | **BM25** (rank_bm25) | 对小规模、高密度领域（30-100 doc）效果好 + 零模型启动 + 可解释 |
| 分词 | jieba (CJK) + ascii split | 简单可靠 |
| 语料 | 自建 30 条（USDA + 中国食物成分表 + WHO） | 可信源、显式 source |
| 分数门槛 | None（默认） | BM25 IDF 在小语料常 ≤ 0，硬卡阈值会全过滤 |
| 切换 | 接口预留 dense | W4 替换为 qdrant + bge-m3 一行调用即可 |

## 端到端 demo 真实跑通

```bash
$ bash scripts/dev.sh demo-supervisor data/test_images/food.jpeg \
    "我目标减脂，这餐够吗？" jason

>>> visited coaches: ['nutrition', 'fitness']

[nutrition]  rag_hits=4  had_image=True  had_profile=True
"这餐提供了约 994 kcal，蛋白质 76.3g 非常充足，但脂肪 60.3g 偏高，
 占能量比例超过 50%，建议适当减少坚果和牛油果的份量。你日均目标 1700 kcal，
 这餐约占 58%...优先选择三文鱼和牛油果中的优质来源，控制在总能量的
 20-35% 之间 (principle:fat_quality)。 (food:坚果混合, principle:fat_quality)"

  • food:鸡胸肉      (USDA FoodData Central)
  • food:三文鱼      (USDA FoodData Central + AHA 推荐)
  • food:坚果混合    (中国食物成分表 + 中国居民膳食指南2022)
  • principle:fat_quality  (WHO 营养指南)

[fitness]  placeholder (W3 D2)
```

## 测试覆盖

```
tests/rag/test_retriever.py             # 9
  - 中英混合分词
  - BM25 基础 / tag_filter / min_score / 空 query / 空语料
  - 真语料对典型问题的 top-5 召回（5 个 case）

tests/agents/test_supervisor_and_graph.py # 8
  - 启发式：image / fitness / data / 模糊
  - 主图：图片→nutrition / 跑步问题→fitness / handoff loop guard / "end"路径
```

## 接下来

- **W3 D2**：Fitness Coach + 训练动作库 RAG（卧推/深蹲/拉伸/恢复）+ 与 nutrition 的真实双向 handoff
- **W3 D3**：Data Analyst 节点（聚合 + 图表生成）
- **W3 D4-5**：完善 Supervisor LLM tie-breaker prompt；多轮对话 checkpoint（PostgresCheckpointer）

## 设计取舍记录

| 选择 | 备选 | 我们选这个的原因 |
|---|---|---|
| LangGraph Command(update, goto) | 状态返回 + 边判断 | Command 模式更简洁、可读、test 友好 |
| BM25 over dense | bge-m3 + Qdrant | 30 条领域文档、零模型启动、易解释 |
| Coach 内调 FoodRecognizer | MCP subprocess | 每次 spawn 子进程开销大；Coach 已在主进程 |
| 启发式 + LLM 二选一 | 纯 LLM | 90% 用户输入启发式秒级解决；省 token、降延迟 |
| In-process recognizer reuse | 重新走 MCP | MCP 跨进程价值在"被外部 client 用"，主进程内直调更快 |
