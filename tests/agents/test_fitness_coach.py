"""Fitness Coach + bidirectional handoff tests (W3 D2)."""

from __future__ import annotations

import pytest


# ---------- training corpus & retriever ----------


def test_fitness_corpus_builds_and_has_safety_doc():
    from backend.app.rag.seeds.fitness_seed import build_fitness_corpus

    docs = build_fitness_corpus()
    assert len(docs) >= 25
    ids = {d.id for d in docs}
    # Must contain at least one safety red-line.
    assert "safety:chest_pain_red_flag" in ids
    # Each doc must have non-empty text and a source.
    for d in docs:
        assert d.text.strip()
        assert d.source.strip()


def test_fitness_retriever_finds_running_doc():
    from backend.app.rag import BM25Retriever
    from backend.app.rag.seeds.fitness_seed import build_fitness_corpus

    r = BM25Retriever(build_fitness_corpus())
    hits = r.search("跑步 步频 落地 受伤 提速", k=4)
    assert any("running" in h.doc.tags for h in hits), [h.doc.id for h in hits]


def test_fitness_retriever_tag_filter_safety():
    from backend.app.rag import BM25Retriever
    from backend.app.rag.seeds.fitness_seed import build_fitness_corpus

    r = BM25Retriever(build_fitness_corpus())
    hits = r.search("胸痛 头晕", k=4, tag_filter="safety")
    assert hits
    for h in hits:
        assert "safety" in h.doc.tags


# ---------- _pick_tag_filter trigger detection ----------


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("训练时突然胸痛、压榨感", "safety"),
        ("最近膝盖痛，跑步要不要停", "recovery"),
        ("做 HIIT 怎么入门", "cardio"),
        ("跑步 5 公里如何提速", "running"),
        ("深蹲 5x5 怎么安排", "strength"),
        ("普通的健康建议", None),
    ],
)
def test_pick_tag_filter(msg, expected):
    from backend.app.agents.nodes.fitness_coach import _pick_tag_filter

    assert _pick_tag_filter(msg) == expected


# ---------- coach node + graph integration ----------


@pytest.fixture
async def temp_app(tmp_path, monkeypatch):
    """Same shape as supervisor tests: isolated DB + mocked router."""
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter
    rt.get_router.cache_clear()

    mock = LLMRouter({
        # main_chat is used by both nutrition + fitness coaches.
        # Its reply triggers a HANDOFF based on the *prompt* — we keep
        # it generic and tag-stable so it doesn't accidentally cause loops.
        "main_chat": [MockProvider(
            name="mock-main", succeed=True,
            reply="周里程稳步加 10% 即可。 (principle:running_10pct)",
        )],
        "router":    [MockProvider(name="mock-router", succeed=True, reply="fitness")],
        "vision":    [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: mock._providers)
    rt.get_router.cache_clear()

    from backend.app.db import init_db
    await init_db()
    yield
    rt.get_router.cache_clear()
    await eng.dispose_engine()


@pytest.mark.asyncio
async def test_fitness_coach_node_returns_answer(temp_app):
    """Direct node invocation: should produce a CoachAnswer with citations."""
    from backend.app.agents.nodes.fitness_coach import fitness_coach_node
    from backend.app.db import session_scope, repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "uF", goal="endurance", weight_kg=68.0)
        await repo.add_activity(
            s, "uF", type="run", duration_min=30, intensity="medium",
            calories_burned=320,
        )

    cmd = await fitness_coach_node({
        "user_id": "uF", "user_message": "我刚跑了 5 公里，怎么继续提速",
    })
    upd = cmd.update
    assert upd["visited_coaches"] == ["fitness"]
    answer = upd["coach_answers"][0]
    assert answer["coach"] == "fitness"
    assert answer["text"]
    # citations should include something running/principle related
    assert len(answer["citations"]) >= 1
    assert answer["metadata"]["weekly_minutes"] > 0


@pytest.mark.asyncio
async def test_fitness_coach_self_handoff_blocked(temp_app, monkeypatch):
    """Even if the LLM tries to HANDOFF: fitness, the node must drop it."""
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter

    sticky = LLMRouter({
        "main_chat": [MockProvider(
            name="mock-sticky", succeed=True,
            reply="多喝水 (principle:who_aerobic_dose)\nHANDOFF: fitness",
        )],
        "router":    [MockProvider(succeed=True, reply="fitness")],
        "vision":    [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: sticky._providers)
    rt.get_router.cache_clear()

    from backend.app.agents.nodes.fitness_coach import fitness_coach_node
    cmd = await fitness_coach_node({"user_id": "uX", "user_message": "随便聊聊运动"})
    assert cmd.update.get("handoff_to") is None  # self-handoff filtered


@pytest.mark.asyncio
async def test_fitness_to_nutrition_handoff_via_keyword(temp_app):
    """When the user asks fitness about meals, fitness should hand off to nutrition."""
    from backend.app.agents.nodes.fitness_coach import fitness_coach_node

    cmd = await fitness_coach_node({
        "user_id": "uH", "user_message": "训练完应该怎么吃才能恢复？",
    })
    assert cmd.update.get("handoff_to") == "nutrition"


@pytest.mark.asyncio
async def test_full_graph_fitness_then_nutrition(temp_app):
    """End-to-end: heuristic routes fitness first, fitness hands off to nutrition,
    supervisor honors the explicit handoff, and finalize merges both."""
    from backend.app.agents.main_graph import build_main_graph
    from backend.app.db import session_scope, repository as repo

    async with session_scope() as s:
        await repo.upsert_user(s, "uN", goal="muscle_gain", weight_kg=72.0)

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "uN",
        # heuristic: fitness=3 ("力量"+"训练"+"健身"), nutrition=1 ("吃") → fitness wins
        # then fitness body has "吃" → reverse handoff to nutrition
        "user_message": "我刚做完力量训练健身，应该怎么吃才能恢复？",
    })
    visited = out.get("visited_coaches") or []
    assert visited == ["fitness", "nutrition"], visited
    answers = out.get("coach_answers") or []
    assert {a["coach"] for a in answers} == {"fitness", "nutrition"}
    # finalize must merge → final_answer non-empty
    assert out.get("final_answer")


@pytest.mark.asyncio
async def test_full_graph_safety_first_when_red_flag(temp_app):
    """A red-flag message must produce a safety-tagged citation in the output."""
    from backend.app.agents.main_graph import build_main_graph

    g = build_main_graph()
    out = await g.ainvoke({
        "user_id": "uS",
        "user_message": "今天跑步时突然胸痛、压榨感，是怎么回事？",
    })
    cites = out.get("final_citations") or []
    assert any("safety" in (c.get("tags") or []) for c in cites), cites
