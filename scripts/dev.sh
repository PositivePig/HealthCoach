#!/usr/bin/env bash
# W1 一键检查脚本：依赖 → 容器(可选) → 测试 → 启动后端
# Usage: bash scripts/dev.sh [up|test|run|down|smoke|sync]

set -euo pipefail

cd "$(dirname "$0")/.."

# CephFS / 分布式文件系统兼容
export UV_LINK_MODE=copy

cmd="${1:-help}"

has_docker() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

case "$cmd" in
  sync)
    echo ">>> uv sync (with UV_LINK_MODE=copy)"
    uv sync
    ;;
  up)
    if has_docker; then
      echo ">>> docker compose -f docker-compose.optional.yml up -d"
      docker compose -f docker-compose.optional.yml up -d
      sleep 5
      docker compose -f docker-compose.optional.yml ps
    else
      echo ">>> docker not available — using no-docker dev profile (see ADR/0006)."
      echo "    Storage: SQLite (./data/healthcoach.db)"
      echo "    Vector:  Qdrant embedded (./data/qdrant)"
      echo "    Tracing: Langfuse Cloud (configured in .env)"
      mkdir -p data
    fi
    ;;
  test)
    echo ">>> running pytest"
    uv run pytest -v
    ;;
  run)
    echo ">>> starting FastAPI on http://localhost:8000"
    uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
    ;;
  smoke)
    BASE="http://127.0.0.1:8000"
    echo ">>> hitting $BASE/health"
    curl -s "$BASE/health" | python -m json.tool
    echo
    echo ">>> POST /chat (non-stream)"
    curl -s -X POST "$BASE/chat" \
      -H "Content-Type: application/json" \
      -d '{"message":"你好，介绍一下你自己"}' | python -m json.tool
    echo
    echo ">>> SSE /chat/stream (first ~30 events)"
    curl -N -s -G "$BASE/chat/stream" \
      --data-urlencode "message=用一句话告诉我健康早餐怎么吃" \
      -o /tmp/hc_sse.out --max-time 30 || true
    head -c 4000 /tmp/hc_sse.out
    echo
    echo ">>> events: $(grep -c '^event:' /tmp/hc_sse.out)"
    ;;
  mcp-smoke)
    echo ">>> in-process MCP stdio smoke test (mock mode)"
    uv run python scripts/smoke_food_vlm_stdio.py 2>/tmp/mcp_stderr.log
    echo "--- server stderr ---"
    head -10 /tmp/mcp_stderr.log
    ;;
  mcp-smoke-real)
    img="${2:-data/test_images/meal.jpg}"
    if [ ! -f "$img" ]; then
      echo "image not found: $img"
      echo "Usage: bash scripts/dev.sh mcp-smoke-real <image_path>"
      exit 1
    fi
    echo ">>> real Qwen-VL smoke on $img"
    uv run python scripts/smoke_food_vlm_stdio.py --real --image "$img" --hint "${3:-}" 2>/tmp/mcp_stderr.log
    ;;
  mcp-inspect)
    echo ">>> launching MCP Inspector (browser UI)"
    echo "    target: food_vlm server (mock mode)"
    echo "    open the printed URL in your browser, click 'Connect'."
    echo "    if dev machine has no GUI browser, forward port to your laptop:"
    echo "      ssh -L 5173:localhost:5173 -L 6277:localhost:6277 <this-host>"
    echo
    npx --yes @modelcontextprotocol/inspector \
      "$(uv run which python)" \
      -m backend.app.mcp_servers.food_vlm.server --mock
    ;;
  mcp-inspect-db)
    echo ">>> MCP Inspector → health_db server"
    npx --yes @modelcontextprotocol/inspector \
      "$(uv run which python)" \
      -m backend.app.mcp_servers.health_db.server
    ;;
  db-reset)
    f="${SQLITE_PATH:-./data/healthcoach.db}"
    if [ -f "$f" ]; then
      echo ">>> removing $f"
      rm -f "$f"
    else
      echo ">>> no db at $f"
    fi
    ;;
  demo-v2)
    img="${2:-data/test_images/food.jpeg}"
    msg="${3:-这餐怎么样？我目标是减脂}"
    uid="${4:-jason}"
    if [ ! -f "$img" ]; then
      echo "image not found: $img"; exit 1
    fi
    echo ">>> running W2D2 demo (food_vlm + health_db + LLM synth)"
    uv run python scripts/demo_nutrition_v2.py --image "$img" --message "$msg" --user-id "$uid"
    ;;
  demo-scheduler)
    uid="${2:-jason}"
    echo ">>> running W2D3 demo: register daily_report → run_now → HITL approve"
    uv run python scripts/demo_scheduler.py --user-id "$uid"
    ;;
  demo-w2-loop)
    img="${2:-data/test_images/food.jpeg}"
    uid="${3:-jason}"
    echo ">>> running W2 closing demo (full proactive loop)"
    uv run python scripts/demo_w2_loop.py --image "$img" --user-id "$uid"
    ;;
  demo-supervisor)
    img="${2:-data/test_images/food.jpeg}"
    msg="${3:-我目标减脂，这餐够吗？}"
    uid="${4:-jason}"
    echo ">>> running W3 D1 demo (Supervisor + Nutrition Coach + RAG)"
    uv run python scripts/demo_supervisor.py --image "$img" --message "$msg" --user-id "$uid"
    ;;
  demo-fitness)
    msg="${2:-最近膝盖前侧痛，跑步要不要停？周里程能恢复吗}"
    uid="${3:-jason}"
    echo ">>> running W3 D2 demo (Fitness Coach + 训练库 RAG)"
    uv run python scripts/demo_fitness.py --message "$msg" --user-id "$uid"
    ;;
  demo-dual-handoff)
    msg="${2:-我刚做完力量训练健身，应该怎么吃才能恢复，蛋白补多少？}"
    uid="${3:-jason}"
    echo ">>> running W3 D2 demo (双向 handoff fitness ⇄ nutrition)"
    uv run python scripts/demo_dual_handoff.py --message "$msg" --user-id "$uid"
    ;;
  demo-mental)
    msg="${2:-我最近压力很大，失眠怎么办？}"
    uid="${3:-jason}"
    echo ">>> running W4 D1 demo (Mental Coach + redline detection)"
    uv run python scripts/demo_mental.py --message "$msg" --user-id "$uid"
    ;;
  demo-mental-scenarios)
    echo ">>> running W4 D1 demo (all scenarios)"
    uv run python scripts/demo_mental.py
    ;;
  mcp-inspect-sched)
    echo ">>> MCP Inspector → scheduler server"
    npx --yes @modelcontextprotocol/inspector \
      "$(uv run which python)" \
      -m backend.app.mcp_servers.scheduler.server
    ;;
  mcp-inspect-notify)
    echo ">>> MCP Inspector → notify server"
    npx --yes @modelcontextprotocol/inspector \
      "$(uv run which python)" \
      -m backend.app.mcp_servers.notify.server
    ;;
  db-init)
    echo ">>> creating tables in $(grep ^SQLITE_PATH .env 2>/dev/null || echo './data/healthcoach.db')"
    uv run python -c "import asyncio; from backend.app.db import init_db; asyncio.run(init_db())"
    ;;
  db-stats)
    uv run python -c "
import asyncio
from backend.app.db import session_scope
from backend.app.db import repository as repo
from sqlalchemy import select, func
from backend.app.db.models import User, Meal, Activity, Vital

async def stats():
    async with session_scope() as s:
        for cls in (User, Meal, Activity, Vital):
            n = (await s.execute(select(func.count()).select_from(cls))).scalar()
            print(f'{cls.__tablename__}: {n}')

asyncio.run(stats())
"
    ;;
  demo-nutrition)
    image="${2:-data/test_images/food.jpeg}"
    user="${3:-jason}"
    msg="${4:-这是我午餐，请评估}"
    echo ">>> end-to-end nutrition demo: image=$image user=$user"
    uv run python scripts/demo_nutrition_agent.py \
      --image "$image" --user-id "$user" --message "$msg"
    ;;
  down)
    if has_docker; then
      docker compose down
    else
      echo ">>> docker not available, nothing to stop."
    fi
    ;;
  help|*)
    cat <<'EOF'
HealthCoachAgent dev helper

Commands:
  sync             - uv sync (UV_LINK_MODE=copy, CephFS-safe)
  up               - start postgres + qdrant + langfuse (skipped if no docker)
  test             - run pytest
  run              - start FastAPI dev server
  smoke            - curl /health + /chat + /chat/stream
  down             - stop docker containers (if docker available)

W2 (MCP servers):
  mcp-smoke           - run food_vlm in mock mode via stdio (no API call)
  mcp-smoke-real      - run food_vlm with real Qwen-VL on a real image
                        usage: bash scripts/dev.sh mcp-smoke-real <image> [hint]
  mcp-inspect         - MCP Inspector → food_vlm
  mcp-inspect-db      - MCP Inspector → health_db
  mcp-inspect-sched   - MCP Inspector → scheduler
  mcp-inspect-notify  - MCP Inspector → notify
  demo-v2             - W2D2: identify image → save to DB → coach answer
                        usage: bash scripts/dev.sh demo-v2 <image> [message] [user_id]
  demo-scheduler      - W2D3: register daily_report → run_now → HITL
                        usage: bash scripts/dev.sh demo-scheduler [user_id]
  demo-w2-loop        - W2 closing demo: full proactive loop (5 steps)
                        usage: bash scripts/dev.sh demo-w2-loop [image] [user_id]
  db-reset            - rm the SQLite database file

Typical W2 daily flow:
  1. bash scripts/dev.sh test                             # pytest
  2. bash scripts/dev.sh mcp-smoke                        # stdio mock
  3. bash scripts/dev.sh mcp-smoke-real data/test_images/meal.jpg
  4. bash scripts/dev.sh demo-v2 data/test_images/food.jpeg
  5. bash scripts/dev.sh mcp-inspect / mcp-inspect-db      # browser UI
EOF
    ;;
esac
