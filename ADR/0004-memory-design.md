# ADR 0004 - 三层记忆设计：Episodic + Semantic + Procedural

- **日期**：2026-05-18
- **状态**：Accepted

## 背景

健康教练必须"懂你"——长期记住你的过敏、目标、伤病、偏好、最近吃了什么、最近练得怎样。  
单纯把所有历史塞 prompt 不可行（context 爆 + 信息淹没）。  
需要分层、可检索、可更新、可遗忘。

## 决策

按 **认知科学三层记忆模型** 设计：

| 层 | 类比 | 存什么 | 存储 | 召回方式 |
|---|---|---|---|---|
| Episodic | "事件回忆" | 每餐、每次运动、每次对话片段 | Postgres + TimescaleDB | 时间窗 + filter |
| Semantic | "知识/概念" | 用户画像、过敏、目标、伤病史 | Qdrant 向量库 | 语义检索 + 标签 |
| Procedural | "习惯/技能" | 沟通风格、提醒偏好 | Postgres KV | 直接读 |

辅以 **Mem0** 作为通用记忆层（自动抽取 + 反思），与三层并存：
- Mem0 处理通用对话事实（"我喜欢吃辣"这种）
- 三层处理结构化健康数据

## 各层详解

### Episodic（事件层）

**特征**：高频写入、按时间检索、最终需归档

```python
class EpisodicStore:
    async def add(self, user_id, kind: Literal["meal","activity","vital","chat"], 
                  ts: datetime, payload: dict): ...
    async def query(self, user_id, kind=None, days=7, limit=50) -> list[dict]: ...
    async def aggregate(self, user_id, kind, range, bucket="day") -> list[dict]: ...
```

**归档策略**：
- 30 天前的 episodic 触发"压缩"——LLM 生成"这周营养摘要"等高级事件，原始保留但不进上下文
- 90 天前自动只保留摘要

**存储**：TimescaleDB hypertable，自动按时间分区

### Semantic（语义层）

**特征**：低频写入、语义检索、严肃事实

```python
class SemanticStore:
    async def add_fact(self, user_id, fact: str, tags: list[str], confidence: float): ...
    async def search(self, user_id, query: str, k=5) -> list[Fact]: ...
    async def list_by_tag(self, user_id, tag: str) -> list[Fact]: ...
    async def remove(self, user_id, fact_id): ...
```

**写入触发**：
- 用户注册问卷 → 批量写入
- 对话中检测到关键事实（"我对花生过敏"）→ 提取 → 用户确认 → 写入
- 用户在 settings/profile 直接编辑

**冲突处理**：
- 新事实与旧事实冲突时（"目标改成增肌了"），保留两条 + 时间戳，最新的标 `current=true`
- 严重冲突（如过敏信息）必须用户确认

**存储**：Qdrant collection per user，payload 存原文 + tags + confidence

### Procedural（程序层）

**特征**：纯 KV、读多写少、影响所有 Coach 风格

```python
class ProceduralStore:
    async def get(self, user_id) -> dict: ...
    # 返回 {tone:"warm",detail_level:"medium",reminder_time:"22:00",reminder_freq:"daily",...}
    
    async def update(self, user_id, patch: dict): ...
```

**学习方式**：
- 用户主动设置（settings 页面）
- 隐式学习：用户给反馈"太啰嗦了"→ Agent 修改 `detail_level`
- 每周自动 review

## 召回策略（在 Coach Node 内）

```python
async def coach_node(state):
    # 1. Procedural - 沟通风格
    proc = await memory.procedural.get(state.user_id)
    
    # 2. Semantic - 用户画像（永远拉取）
    profile_facts = await memory.semantic.list_by_tag(state.user_id, "profile")
    
    # 3. Semantic - 与当前问题相关的事实
    relevant_facts = await memory.semantic.search(
        state.user_id, state.last_user_msg, k=3
    )
    
    # 4. Episodic - 近期事件（按 Coach 类型筛选）
    if isinstance(self, NutritionCoach):
        recent = await memory.episodic.query(state.user_id, kind="meal", days=7)
    elif isinstance(self, FitnessCoach):
        recent = await memory.episodic.query(state.user_id, kind="activity", days=14)
    ...
    
    # 5. 拼 system prompt
    system = render_prompt(role=self.role, proc=proc, 
                          facts=profile_facts+relevant_facts, recent=recent)
```

## 与 Mem0 的关系

Mem0 作为 **通用对话事实抽取层**：
- 每次对话结束后异步运行 Mem0 抽取
- 抽出来的 fact 写入 Semantic 层（标 `source="mem0"`）
- 三层是**业务结构化层**，Mem0 是**对话非结构化层**
- 互补关系，不冲突

## 隐私与遗忘

- 用户在 `/settings/data` 可：
  - 导出全部三层数据为 JSON
  - 删除单条事实
  - 一键清除所有数据（GDPR-style）
- 心理 Coach 数据加密存储（pgcrypto）
- 不可恢复删除时，向量库也同步清

## 后果

### 优点
- ✅ 可解释：用户能看到 Agent "记得什么"
- ✅ 可控：可改、可删
- ✅ 高效：每次只取相关记忆，不爆 context
- ✅ 学习深度：手写一遍记忆系统，理解透彻

### 缺点
- ⚠️ 复杂度高：需写存储 + 召回 + 抽取 + 归档
- ⚠️ 抽取准确率影响体验 → 用户确认机制兜底

## 落地节奏

- W3：episodic 简单版（写入 + 查询）
- W4：三层完整版 + Mem0 集成
- W5：归档 + 冲突处理
- W7：评估"跨会话记忆准确率"
