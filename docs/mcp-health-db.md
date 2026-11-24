# health_db MCP Server

> 用户健康数据 CRUD + 受限只读 SQL，作为 MCP tool 暴露。  
> 单一职责：Agent 不直接接触数据库连接，只通过 MCP tool 操作业务数据。

---

## 工具列表（10 个）

| Tool | 类型 | 描述 |
|---|---|---|
| `upsert_user_profile` | write | 创建/更新用户画像（目标/身高/体重/过敏/忌口/病史） |
| `get_user_profile` | read | 读取用户画像 |
| `add_meal` | write | 写入一餐（dishes 通常来自 food_vlm） |
| `query_meals` | read | 查询近 N 天餐次（默认 7） |
| `aggregate_nutrition` | read | 汇总近 N 天营养（合计 + 日均） |
| `add_activity` | write | 记录一次运动 |
| `query_activities` | read | 查询近 N 天运动 |
| `add_vital` | write | 记录体征（体重/体脂/HRV/睡眠/心情） |
| `query_vitals` | read | 查询近 N 天体征 |
| `execute_safe_sql` | read-only | **受限**只读 SQL 查询（白名单 + 参数化） |

---

## 数据模型

```
users
  id (PK), name, email, goal, height_cm, weight_kg, target_kcal,
  allergies[], dislikes[], diseases[], created_at

meals (含复合索引 user_id, ts)
  id, user_id, ts, dishes (JSON, RecognizeFoodResult.items),
  total_kcal, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g,
  confidence, source (photo/manual/voice/import), image_path, notes

activities (含复合索引 user_id, ts)
  id, user_id, ts, type (run/walk/strength/yoga/...), duration_min,
  intensity (low/medium/high), hr_avg, calories_burned, notes, source

vitals (含复合索引 user_id, ts)
  id, user_id, ts, weight_kg, body_fat, hrv_ms, sleep_min, mood, notes
```

存储后端：**SQLite**（dev，由 `STORAGE_BACKEND=sqlite` 控制）/ **Postgres**（prod，可平滑切换）。  
SQLAlchemy 抽象 → 切换只需改 `.env` 的一行。

---

## 安全设计（重点）

`execute_safe_sql` 是**唯一**面向 LLM 的灵活查询入口，必须严密把守：

| 防御层 | 实现 |
|---|---|
| **只允许 SELECT / WITH** | 首字符级别拒绝 |
| **禁止多语句** | 出现 `;` 立即拒绝 |
| **禁止 DML/DDL/Pragma** | 正则黑名单：DROP/DELETE/UPDATE/INSERT/ALTER/CREATE/ATTACH/DETACH/PRAGMA/EXEC/TRUNCATE/GRANT/REVOKE/VACUUM/MERGE |
| **禁止注释/转义** | `--`、`/*`、`*/` 全部拒绝 |
| **表白名单** | 只允许 `meals / activities / vitals / users`，其他表（含 `sqlite_master`）一律拒绝 |
| **CTE 别名豁免** | `WITH x AS (...)` 中的 `x` 自动放行 |
| **强制 LIMIT** | 不写 LIMIT 自动追加 200，封顶 1000 |
| **参数化** | 用 `:name` 占位符 + `params` dict，**绝不拼接字符串** |

满足项目工程安全规范 Rule 1（SQL 注入防护）。

测试覆盖（`tests/db/test_safe_sql.py`）：
- 16 个负面用例（DROP / DELETE / UPDATE / 多语句 / 注释 / 注入 payload / 非白名单表 / Pragma / Attach / Truncate / Vacuum / Create / Alter / 空 / Describe / `' OR '1'='1' --`）
- 4 个正面用例（基本 SELECT / 限定列 / CTE / JOIN）
- 1 个真实端到端用例（创建 → 插入 → 参数化 SELECT）

---

## 启动方式

### 1. 直接（LangGraph / Claude Desktop 等 MCP client）

```bash
uv run python -m backend.app.mcp_servers.health_db.server
```

第一次运行会自动创建 SQLite 文件（路径由 `SQLITE_PATH` 控制，默认 `./data/healthcoach.db`），并 `metadata.create_all` 建表。

### 2. dev.sh

```bash
bash scripts/dev.sh demo-v2 data/test_images/food.jpeg     # 端到端 demo
bash scripts/dev.sh mcp-inspect-db                          # 浏览器调试
bash scripts/dev.sh db-reset                                # 清空 SQLite
```

### 3. Claude Desktop 接入

```json
{
  "mcpServers": {
    "health-db": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/HealthCoachAgent",
        "run",
        "python",
        "-m",
        "backend.app.mcp_servers.health_db.server"
      ],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "SQLITE_PATH": "/path/to/HealthCoachAgent/data/healthcoach.db"
      }
    }
  }
}
```

---

## W2 Day 2 完整 demo

```bash
$ bash scripts/dev.sh demo-v2 data/test_images/food.jpeg "我目标减脂"

>>> running graph (recognize -> db_io -> synthesize) ...

--- food_vlm (qwen-vl) ---
  items   : 鸡蛋, 鸡胸肉, 三文鱼, 坚果, 香蕉, 牛油果, 生菜, 圣女果
  kcal    : 996.0
  protein : 75.6g

--- meal saved ---  id=1  ts=2026-05-18T12:05:19+00:00

--- 7-day history ---
  meals       : 1
  avg kcal/d  : 142.3
  avg protein : 10.8g/d

--- coach answer ---
[deepseek/deepseek-chat]
这餐总计约 996 千卡，蛋白质 75.6 克...但你的目标是减脂，
而近 7 天日均仅摄入 142 千卡，这种极端低摄入反而可能降低代谢。
建议将坚果减半至 15 克，并用 2 个蛋白替换 1 个全蛋。
下一步：明天起将日均提升至 1400-1600 千卡...
```

跑第二次后，`avg_kcal_per_day` 自动累加，教练回答会随历史变化。

---

## 与 food_vlm 的协作

```
       LangGraph
       /         \
  food_vlm      health_db
   (subprocess) (subprocess)
       │            │
       ▼            ▼
   Qwen-VL     SQLite/Postgres
       │            ▲
       └─→─[items]──┘
              add_meal
```

两个 server 完全独立、单一职责，可被不同 client 独立使用。

---

## v2 计划（W4+）

- [ ] Alembic 迁移管理（W4 切 Postgres 时启用）
- [ ] `query_by_natural_language`：把 LLM 生成的 SQL 经过 safe_sql 校验后执行（Agentic SQL）
- [ ] Row-level user 隔离强制（防 LLM 写跨用户 SQL）
- [ ] 字段级脱敏（心理 Coach 数据加密）
