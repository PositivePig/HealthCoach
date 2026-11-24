"""W3 D3 finalize node tests (3-mode merging + few-shot router)."""

from __future__ import annotations

import pytest

from backend.app.agents.supervisor import (
    _dedup_citations,
    _has_safety_citation,
    finalize_node,
)


# ---------- pure helpers ----------


def test_has_safety_citation_true():
    answers = [
        {"coach": "fitness", "citations": [
            {"id": "x", "tags": ["safety", "redline"]},
        ]},
    ]
    assert _has_safety_citation(answers) is True


def test_has_safety_citation_false():
    answers = [
        {"coach": "fitness", "citations": [{"id": "x", "tags": ["recovery"]}]},
        {"coach": "nutrition", "citations": []},
    ]
    assert _has_safety_citation(answers) is False


def test_dedup_citations_keeps_first_occurrence():
    answers = [
        {"citations": [{"id": "a", "source": "s1"}, {"id": "b", "source": "s2"}]},
        {"citations": [{"id": "a", "source": "DUP"}, {"id": "c", "source": "s3"}]},
    ]
    out = _dedup_citations(answers)
    assert [c["id"] for c in out] == ["a", "b", "c"]
    # first occurrence wins
    assert out[0]["source"] == "s1"


# ---------- finalize_node empty/passthrough ----------


@pytest.mark.asyncio
async def test_finalize_empty():
    out = await finalize_node({"coach_answers": [], "visited_coaches": []})
    assert out["final_mode"] == "empty"
    assert out["final_answer"] == "（暂无可回答内容）"


@pytest.mark.asyncio
async def test_finalize_passthrough_single_coach():
    state = {
        "coach_answers": [{
            "coach": "nutrition",
            "text": "建议每餐 25-40g 蛋白",
            "citations": [{"id": "p", "tags": ["principle"]}],
            "metadata": {"provider": "deepseek", "model": "deepseek-chat"},
        }],
        "visited_coaches": ["nutrition"],
    }
    out = await finalize_node(state)
    assert out["final_mode"] == "passthrough"
    assert out["final_answer"] == "建议每餐 25-40g 蛋白"
    assert out["final_provider"] == "deepseek"


# ---------- finalize_node multi-coach modes (LLM mocked) ----------


@pytest.fixture
def mock_main_chat(monkeypatch):
    """Patch the LLM router so finalize_node's LLM call is deterministic."""
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter

    rt.get_router.cache_clear()
    mock = LLMRouter({
        "main_chat": [MockProvider(name="mock", succeed=True,
                                   reply="MERGED_REPLY")],
        "router": [MockProvider(name="mock", succeed=True, reply="end")],
        "vision": [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: mock._providers)
    rt.get_router.cache_clear()
    yield
    rt.get_router.cache_clear()


@pytest.mark.asyncio
async def test_finalize_primary_addon_no_safety(mock_main_chat):
    state = {
        "coach_answers": [
            {"coach": "fitness", "text": "fit answer",
             "citations": [{"id": "p1", "tags": ["principle"]}],
             "metadata": {"provider": "x"}},
            {"coach": "nutrition", "text": "nut answer",
             "citations": [{"id": "p2", "tags": ["principle"]}],
             "metadata": {"provider": "x"}},
        ],
        "visited_coaches": ["fitness", "nutrition"],
    }
    out = await finalize_node(state)
    assert out["final_mode"] == "primary_addon"
    assert out["final_answer"] == "MERGED_REPLY"
    # citations from both, deduped
    assert {c["id"] for c in out["final_citations"]} == {"p1", "p2"}


@pytest.mark.asyncio
async def test_finalize_safety_first_when_red_flag(mock_main_chat):
    state = {
        "coach_answers": [
            {"coach": "fitness", "text": "stop training, see doctor",
             "citations": [{"id": "safety:chest_pain_red_flag",
                            "tags": ["safety", "redline"]}],
             "metadata": {"provider": "x"}},
            {"coach": "nutrition", "text": "hydrate well",
             "citations": [{"id": "principle:water", "tags": ["principle"]}],
             "metadata": {"provider": "x"}},
        ],
        "visited_coaches": ["fitness", "nutrition"],
    }
    out = await finalize_node(state)
    assert out["final_mode"] == "safety_first"
    assert any("safety" in (c.get("tags") or [])
               for c in out["final_citations"])


@pytest.mark.asyncio
async def test_finalize_falls_back_when_llm_fails(monkeypatch):
    """If the merge LLM call raises ProviderError, finalize must concat & continue."""
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter

    rt.get_router.cache_clear()
    failing = LLMRouter({
        "main_chat": [MockProvider(name="m", succeed=False)],
        "router": [MockProvider(name="m", succeed=True, reply="end")],
        "vision": [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: failing._providers)
    rt.get_router.cache_clear()

    state = {
        "coach_answers": [
            {"coach": "fitness", "text": "fit", "citations": [],
             "metadata": {"provider": "x"}},
            {"coach": "nutrition", "text": "nut", "citations": [],
             "metadata": {"provider": "x"}},
        ],
        "visited_coaches": ["fitness", "nutrition"],
    }
    out = await finalize_node(state)
    assert out["final_provider"] == "fallback-concat"
    # the concat fallback contains both coach texts
    assert "fit" in out["final_answer"]
    assert "nut" in out["final_answer"]


# ---------- llm router parser robustness ----------


@pytest.mark.asyncio
async def test_llm_route_parses_quoted_reply(monkeypatch):
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter
    from backend.app.agents.supervisor import _llm_route

    rt.get_router.cache_clear()
    quoted = LLMRouter({
        "main_chat": [MockProvider(name="m", succeed=True, reply="x")],
        "router": [MockProvider(name="m", succeed=True, reply='"nutrition"')],
        "vision": [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: quoted._providers)
    rt.get_router.cache_clear()

    out = await _llm_route({"user_message": "随便聊"})
    assert out == "nutrition"


@pytest.mark.asyncio
async def test_llm_route_parses_explained_reply(monkeypatch):
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter
    from backend.app.agents.supervisor import _llm_route

    rt.get_router.cache_clear()
    chatty = LLMRouter({
        "main_chat": [MockProvider(name="m", succeed=True, reply="x")],
        "router": [MockProvider(name="m", succeed=True,
                                 reply="答: fitness")],
        "vision": [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: chatty._providers)
    rt.get_router.cache_clear()

    out = await _llm_route({"user_message": "你好"})
    assert out == "fitness"


@pytest.mark.asyncio
async def test_llm_route_invalid_reply_falls_to_end(monkeypatch):
    from backend.app.llm import router as rt
    from backend.app.llm.providers.mock import MockProvider
    from backend.app.llm.router import LLMRouter
    from backend.app.agents.supervisor import _llm_route

    rt.get_router.cache_clear()
    invalid = LLMRouter({
        "main_chat": [MockProvider(name="m", succeed=True, reply="x")],
        "router": [MockProvider(name="m", succeed=True, reply="hello world")],
        "vision": [],
    })
    monkeypatch.setattr("backend.app.llm.router._build_default_providers",
                        lambda settings: invalid._providers)
    rt.get_router.cache_clear()

    out = await _llm_route({"user_message": "hi"})
    assert out == "end"
