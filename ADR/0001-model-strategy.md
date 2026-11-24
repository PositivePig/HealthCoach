# ADR 0001 - 模型调用策略：API 优先 + 本地回退

- **日期**：2026-05-18
- **状态**：Accepted

## 背景

Agent 项目需要大量 LLM 调用：主对话、视觉识别、意图路由、Embedding。  
作者拥有部分 GPU 资源（来自 PalmprintQuality-R1 项目环境），但日常开发主要在普通工位机进行。  
需要在 **效果、成本、延迟、隐私、稳定性** 之间权衡。

## 决策

采用 **API 优先 + 本地回退** 的多 provider 策略，由 `app/llm/router.py` 统一封装。

### 路由表

| 角色 | 优先 | 二选 | 兜底（本地） |
|---|---|---|---|
| `main_chat`（主对话/教练） | DeepSeek-V3.2 | Claude Sonnet 4.5 | Qwen3-14B（vLLM 量化） |
| `vision`（食物识别） | Qwen3-VL-Plus | GPT-5V | Qwen3-VL-7B（本地） |
| `router`（意图分类） | DeepSeek-V3.2 | — | Qwen3-4B（本地） |
| `embedding` | bge-m3（**直接本地**） | — | — |

### 触发回退的条件

- HTTP 5xx / 超时
- RateLimitError / QuotaExceeded
- 显式 `force_local=True` 标志（敏感数据时由调用方指定）

### 接口规范

```python
class LLMProvider(Protocol):
    name: str
    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs
    ) -> AsyncIterator[Chunk] | Response: ...
```

所有 provider 实现同一接口；上层 Coach 节点不感知具体厂商。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 纯本地部署 | 启动慢、显存占用大，影响开发迭代速度 |
| 纯 API | 隐私敏感场景、无网开发不便 |
| 单 API（如只用 Claude） | 单点故障、成本高、被限流即挂 |

## 后果

### 优点
- ✅ 成本可控：日常 ¥20-100/月
- ✅ 故障韧性：任一 provider 挂了仍可用
- ✅ 隐私保护：心理 Coach 等敏感场景可强制本地
- ✅ 开发顺滑：不依赖 GPU 启动

### 缺点
- ⚠️ 复杂度提升：需维护多个 provider 适配器
- ⚠️ 模型行为差异：不同模型 prompt 可能要分别调优 → 评估集帮忙发现

### 落地动作
- W1 完成 `router.py` + DeepSeek/Qwen-VL 适配器 + 故意失败的回退测试
- W4 加 Claude 适配器（关键决策时使用）
- W5 加本地 vLLM 适配器（如有空闲 GPU）

## 配置示例

```env
# .env
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=...        # Qwen
ANTHROPIC_API_KEY=sk-ant-... # Claude（可选）
OPENAI_API_KEY=...           # GPT-5V（可选）

LOCAL_VLLM_BASE=http://10.0.0.5:8000   # 可选
LOCAL_QWEN_MODEL=Qwen/Qwen3-14B-Instruct-AWQ
```
