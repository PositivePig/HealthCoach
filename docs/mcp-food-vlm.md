# food_vlm MCP Server

> 单一职责的 MCP server：把"图片 → 结构化营养信息"作为一个 tool 暴露出去。

---

## 工具

### `recognize_food`

**输入**：
- `image` *(string, required)*：本地路径 / base64 / data URL / http(s) URL
- `hint` *(string, optional)*：用户文字提示（如"这是减脂餐"）

**输出**：`RecognizeFoodResult`（结构化）+ TextContent JSON 文本

```json
{
  "items": [
    {
      "name": "煎豆腐",
      "estimated_grams": 120,
      "kcal": 240,
      "protein_g": 16,
      "carbs_g": 12,
      "fat_g": 14,
      "fiber_g": 3,
      "confidence": 0.85
    }
  ],
  "total_kcal": 240,
  "total_protein_g": 16,
  "total_carbs_g": 12,
  "total_fat_g": 14,
  "overall_confidence": 0.85,
  "notes": "餐盘较大，份量估算保守。",
  "image_quality": "good",
  "mode": "qwen-vl"
}
```

---

## 三种运行模式

| `mode` 字段 | 触发 | 说明 |
|---|---|---|
| `qwen-vl` | 配置了 `DASHSCOPE_API_KEY` | 真实调用 Qwen-VL-Plus |
| `mock` | 没配 key 或 `--mock` 开关 | 离线确定性假数据，测试用 |
| `fallback` | Qwen-VL 调用失败或 JSON 解析失败 | 返回降级结果（confidence=0），便于 UI 提示 |

---

## 启动方式

### 1. 直接（本项目 LangGraph 用，stdio）

```bash
# 真实模式
uv run python -m backend.app.mcp_servers.food_vlm.server

# 强制 mock（不需要 key，离线开发）
uv run python -m backend.app.mcp_servers.food_vlm.server --mock
```

### 2. 通过 `dev.sh`（最常用）

```bash
bash scripts/dev.sh mcp-smoke                                    # 端到端 mock
bash scripts/dev.sh mcp-smoke-real data/test_images/meal.jpg     # 真实 Qwen-VL
bash scripts/dev.sh mcp-inspect                                  # MCP Inspector UI
```

### 3. MCP Inspector（浏览器 UI 调试）

```bash
bash scripts/dev.sh mcp-inspect
# 浏览器打开打印的 URL → Connect → Tools → recognize_food
```

无 GUI 浏览器的开发机？把端口转发到本地：

```bash
# 在本地（你的笔记本）执行
ssh -L 5173:localhost:5173 -L 6277:localhost:6277 <dev-host>
```

### 4. Claude Desktop 接入（证明 MCP 通用性）

把以下加到 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或对应 Windows 路径：

```json
{
  "mcpServers": {
    "food-vlm": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/HealthCoachAgent",
        "run",
        "python",
        "-m",
        "backend.app.mcp_servers.food_vlm.server"
      ],
      "env": {
        "DASHSCOPE_API_KEY": "sk-...",
        "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_VL_MODEL": "qwen-vl-plus"
      }
    }
  }
}
```

重启 Claude Desktop → 在对话里"识别这张图的营养"，Claude 会自动调用 `recognize_food`。  
👉 **这一步证明：你写的 MCP server 能被任何 MCP client 复用，而不是绑死本项目。**

### 5. Cursor 接入

`Cursor Settings → MCP → Add Server`，配置同上。

---

## 协议细节

- **MCP SDK**：`mcp>=1.27`
- **传输**：stdio（W2 默认）/ SSE（可选，W8 部署时切换）
- **outputSchema 已声明** → 必须返回 `structuredContent`，本 server 已遵守
- **stdout = JSON-RPC 专用通道**，所有日志走 stderr（已配置）

---

## 单元测试覆盖

```
tests/mcp/test_food_vlm.py        # schema / parser / mock recognizer
tests/mcp/test_food_vlm_server.py # MCP 协议层（list_tools / call_tool / 错误）
```

```bash
uv run pytest tests/mcp -v
# 16 passed
```

---

## 内部数据流

```
       ┌─────────────────┐
       │  MCP Client     │  (LangGraph / Claude Desktop / Cursor / Inspector)
       └────────┬────────┘
                │ stdio JSON-RPC
                ▼
       ┌─────────────────┐
       │  food_vlm       │  Server(name="food-vlm")
       │  Server         │
       └────────┬────────┘
                │ call_tool("recognize_food", {image, hint})
                ▼
       ┌─────────────────┐
       │ FoodRecognizer  │
       └────────┬────────┘
                │
        ┌───────┴────────┐
        │                │
        ▼                ▼
  [no key]         [has key]
  mock_result   OpenAICompatibleProvider
                       │
                       ▼
              Qwen-VL-Plus (DashScope)
                       │
                       ▼
                JSON parse + validate
                       │
                       ▼
              RecognizeFoodResult
```

---

## v2 计划（W4+）

- [ ] 加 `quality_check` tool：检测图片是否模糊/光线差/拍偏（复用 PalmprintQuality-R1 思路）
- [ ] 多张图融合（前后/俯视）
- [ ] 餐前餐后对比（吃了多少）
- [ ] 用户校准（用户改过几次估算 → 学会个人份量基准）
