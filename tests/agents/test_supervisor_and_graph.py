"""Supervisor + main graph tests.

LLM is mocked end-to-end via the LLMRouter MockProvider, so these tests
do not depend on any API key. We validate routing decisions, loop guard,
state merging, and finalization behavior.
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def temp_app(tmp_path, monkeypatch):
    """Each test gets an isolated DB + reset singletons."""
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    # Mock the LLM router so coach + supervisor LLM calls are deterministic.
    # We replace the *router instance* under the cached function — leaves the
    # cache_clear() ability intact for subsequent tests.
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter
    rt.get_router.cache_clear()

    mock = LLMRouter({
        "main_chat": [MockProvider(name="mock-main", succeed=True,
                                   reply="鸡胸肉是优质蛋白来源。建议每餐 25-40g。"
                                         " (food:鸡胸肉, principle:protein_target_general)")],
        "router":    [MockProvider(name="mock-router", succeed=True, reply="nutrition")],
        "vision":    [],
    })

    # Replace the cached singleton: the @lru_cache decorator's cache stores
    # function → return value, but we can also just patch _the singleton_.
    # Simpler approach: monkeypatch the underlying construction.
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: mock._providers)
    rt.get_router.cache_clear()

    # init db
    from backend.app.db import init_db
    await init_db()

    yield
    rt.get_router.cache_clear()
    await eng.dispose_engine()


# ---------- heuristics ----------


def test_heuristic_image_path_routes_nutrition():
    from backend.app.agents.supervisor import _heuristic_route
    assert _heuristic_route({"image_path": "/x.jpg", "user_message": ""}) == "nutrition"


def test_heuristic_obvious_fitness():
    from backend.app.agents.supervisor import _heuristic_route
    assert _heuristic_route(
        {"user_message": "我刚跑步完，做了 30 分钟力量训练"}
    ) == "fitness"


def test_heuristic_obvious_data():
    from backend.app.agents.supervisor import _heuristic_route
    assert _heuristic_route(
        {"user_message": "本周累计吃了几餐？平均热量多少"}
    ) == "data"


def test_heuristic_ambiguous_returns_none():
    from backend.app.agents.supervisor import _heuristic_route
    # No keyword matches at all
    assert _heuristic_route({"user_message": "你好"}) is None


# ---------- end-to-end through the main graph ----------


@pytest.mark.asyncio
async def test_graph_routes_nutrition_when_image(temp_app):
    from backend.app.agents.main_graph import build_main_graph

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "u1",
        "user_message": "看看这餐",
        "image_path": "/non/existent.jpg",  # recognizer will fall back to mock
    })

    assert "nutrition" in (out.get("visited_coaches") or [])
    answers = out.get("coach_answers") or []
    assert len(answers) >= 1
    assert answers[0]["coach"] == "nutrition"
    assert "鸡胸肉" in (out.get("final_answer") or "")
    # Citations attached
    cites = out.get("final_citations") or []
    # nutrition_coach RAG should have produced something
    assert isinstance(cites, list)


@pytest.mark.asyncio
async def test_graph_routes_fitness_for_workout_question(temp_app):
    from backend.app.agents.main_graph import build_main_graph

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "u2",
        "user_message": "我刚跑了 5 公里，心率挺高的",
    })

    visited = out.get("visited_coaches") or []
    assert "fitness" in visited
    assert any(a["coach"] == "fitness" for a in (out.get("coach_answers") or []))


@pytest.mark.asyncio
async def test_graph_loop_guard_caps_at_two_coaches(temp_app):
    """If a coach hands off, supervisor should allow exactly one extra hop."""
    from backend.app.agents.main_graph import build_main_graph
    from backend.app.db import session_scope, repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "u3", goal="cut")

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "u3",
        # message that is nutrition-leading AND mentions running →
        # nutrition_coach detects '跑了' → handoff → fitness
        "user_message": "今天我刚跑完 5 公里，下午这餐够吗？",
        "image_path": "/x.jpg",
    })
    visited = out.get("visited_coaches") or []
    # nutrition first (image), then fitness via handoff
    assert visited == ["nutrition", "fitness"]


@pytest.mark.asyncio
async def test_graph_finalizes_when_no_coach_needed(temp_app, monkeypatch):
    """LLM router returns 'end' → finalize emits empty placeholder."""
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter

    end_router = LLMRouter({
        "main_chat": [MockProvider(succeed=True, reply="x")],
        "router":    [MockProvider(succeed=True, reply="end")],
        "vision":    [],
    })
    monkeypatch.setattr(
        "backend.app.llm.router._build_default_providers",
        lambda settings: end_router._providers,
    )
    rt.get_router.cache_clear()

    from backend.app.agents.main_graph import build_main_graph
    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "u4",
        "user_message": "你好",  # vague greeting → heuristic returns None → llm "end"
    })
    assert out.get("final_answer") == "（暂无可回答内容）"
    assert (out.get("visited_coaches") or []) == []
