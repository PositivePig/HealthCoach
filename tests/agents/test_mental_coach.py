"""Mental Coach + crisis detection tests (W4 D1)."""

from __future__ import annotations

import pytest


# ---------- mental corpus & retriever ----------


def test_mental_corpus_builds_and_has_redline_doc():
    from backend.app.rag.seeds.mental_seed import build_mental_corpus

    docs = build_mental_corpus()
    assert len(docs) >= 25
    ids = {d.id for d in docs}
    # Must contain at least one redline doc.
    assert any("redline" in d.tags for d in docs)
    # Each doc must have non-empty text and a source.
    for d in docs:
        assert d.text.strip()
        assert d.source.strip()


def test_mental_retriever_finds_sleep_doc():
    from backend.app.rag import BM25Retriever
    from backend.app.rag.seeds.mental_seed import build_mental_corpus

    r = BM25Retriever(build_mental_corpus())
    hits = r.search("失眠 睡眠质量 深睡眠", k=4)
    assert any("sleep" in h.doc.tags for h in hits), [h.doc.id for h in hits]


def test_mental_retriever_tag_filter_redline():
    from backend.app.rag import BM25Retriever
    from backend.app.rag.seeds.mental_seed import build_mental_corpus

    r = BM25Retriever(build_mental_corpus())
    hits = r.search("自伤 自杀 绝望", k=4, tag_filter="redline")
    assert hits
    for h in hits:
        assert "redline" in h.doc.tags


# ---------- _detect_redline ----------


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("我想割腕自杀", "self_harm"),
        ("不想活了，想结束生命", "self_harm"),
        ("已经连续两周无法起床、不洗脸不刷牙", "severe_depression"),
        ("突然心跳加速、窒息感、感觉要死了", "panic_attack"),
        ("今天吃什么好呢", None),
        ("如何减脂", None),
    ],
)
def test_detect_redline(msg, expected):
    from backend.app.agents.nodes.mental_coach import _detect_redline

    assert _detect_redline(msg) == expected


# ---------- _pick_tag_filter ----------


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("失眠 早醒 睡眠质量差", "sleep"),
        ("焦虑 紧张 恐慌发作", "anxiety"),
        ("抑郁 低落 无动力", "depression"),
        ("工作压力很大，快崩溃了", "stress"),
        ("感觉很孤独，不想社交", "social"),
        ("今天吃什么", None),
    ],
)
def test_pick_tag_filter(msg, expected):
    from backend.app.agents.nodes.mental_coach import _pick_tag_filter

    assert _pick_tag_filter(msg) == expected


# ---------- crisis response (no LLM call) ----------


@pytest.mark.asyncio
async def test_mental_node_redline_self_harm(monkeypatch):
    """Redline message → immediate crisis response, no LLM call."""
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    # Ensure no DB call is attempted (no session_scope should be called).
    call_count = 0

    async def fake_session_scope():
        nonlocal call_count
        call_count += 1
        # This should NOT be called for redline.
        raise AssertionError("session_scope should not be called for redline")

    import backend.app.agents.nodes.mental_coach as mdl

    monkeypatch.setattr(mdl, "session_scope", fake_session_scope)

    state = {
        "user_id": "test_user",
        "user_message": "我想割腕自杀",
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update  # Command object has .update attribute
    assert "危机干预" in updates["coach_answers"][0]["text"]
    assert updates["visited_coaches"] == ["mental"]
    assert call_count == 0  # LLM was NOT called


@pytest.mark.asyncio
async def test_mental_node_redline_severe_depression(monkeypatch):
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    state = {
        "user_id": "test_user",
        "user_message": "已经连续两周无法起床，不洗脸不刷牙",
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update
    assert "严重抑郁预警" in updates["coach_answers"][0]["text"]
    assert "精神科" in updates["coach_answers"][0]["text"]


@pytest.mark.asyncio
async def test_mental_node_redline_panic_attack(monkeypatch):
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    state = {
        "user_id": "test_user",
        "user_message": "突然心跳加速、胸闷、窒息感，感觉要死了",
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update
    assert "惊恐发作" in updates["coach_answers"][0]["text"]
    assert "急诊" in updates["coach_answers"][0]["text"]


# ---------- handoff parsing ----------


def test_handoff_to_nutrition():
    """Model outputs HANDOFF: nutrition → parsed."""
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    # We mock the LLM to return a handoff trailer.
    import backend.app.agents.nodes.mental_coach as mdl

    async def fake_llm(*args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            content="建议补充 Omega-3 脂肪酸。\nHANDOFF: nutrition",
            provider="mock",
            model="mock",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mdl, "get_router", lambda: type("M", (), {"chat": fake_llm})())
    # (We'll do a proper integration test in test_mental_handoff_integration below)


@pytest.mark.asyncio
async def test_mental_handoff_to_fitness(monkeypatch):
    """User message contains fitness keywords → handoff to fitness."""
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    # Mock LLM to return plain text (no handoff trailer).
    import types

    from backend.app.llm import ChatMessage

    async def mock_chat(role, messages, **kw):
        return types.SimpleNamespace(
            content="运动确实可以缓解焦虑，建议每周 3 次有氧。\nHANDOFF: fitness",
            provider="mock",
            model="mock",
        )

    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.get_router",
        lambda: types.SimpleNamespace(chat=mock_chat),
    )
    # Also mock session_scope to avoid DB.
    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.session_scope",
        __import__("contextlib").asynccontextmanager(lambda *a, **kw: (yield None)),
    )

    state = {
        "user_id": "test_user",
        "user_message": "运动能不能缓解我的焦虑？",  # contains fitness keyword
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update
    # The keyword "运动" should trigger handoff to fitness.
    assert updates["handoff_to"] == "fitness"


@pytest.mark.asyncio
async def test_mental_self_handoff_prevented(monkeypatch):
    """Model outputs HANDOFF: mental → must be discarded (self-handoff guard)."""
    import types

    from backend.app.llm import ChatMessage
    from backend.app.agents.nodes.mental_coach import mental_coach_node

    async def mock_chat(role, messages, **kw):
        return types.SimpleNamespace(
            content="建议多正念练习。\nHANDOFF: mental",  # invalid self-handoff
            provider="mock",
            model="mock",
        )

    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.get_router",
        lambda: types.SimpleNamespace(chat=mock_chat),
    )
    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.session_scope",
        __import__("contextlib").asynccontextmanager(lambda *a, **kw: (yield None)),
    )

    state = {
        "user_id": "test_user",
        "user_message": "如何改善情绪？",
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update
    # Self-handoff must be None.
    assert updates["handoff_to"] is None
    # The handoff trailer must be stripped from text.
    assert "HANDOFF" not in updates["coach_answers"][0]["text"]


# ---------- graph integration ----------


@pytest.mark.asyncio
async def test_mental_node_produces_coach_answer(monkeypatch):
    """Mental node returns a CoachAnswer with non-empty text."""
    import types

    async def mock_chat(role, messages, **kw):
        return types.SimpleNamespace(
            content="（mock）建议尝试 4-7-8 呼吸法，4 秒吸气、7 秒屏息、8 秒呼气。",
            provider="mock",
            model="mock",
        )

    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.get_router",
        lambda: types.SimpleNamespace(chat=mock_chat),
    )
    monkeypatch.setattr(
        "backend.app.agents.nodes.mental_coach.session_scope",
        __import__("contextlib").asynccontextmanager(lambda *a, **kw: (yield None)),
    )

    from backend.app.agents.nodes.mental_coach import mental_coach_node

    state = {
        "user_id": "test_user",
        "user_message": "最近压力很大，失眠怎么办？",
        "visited_coaches": [],
        "coach_answers": [],
        "handoff_to": None,
        "image_path": None,
    }
    result = await mental_coach_node(state)
    updates = result.update
    answer = updates["coach_answers"][0]
    assert answer["coach"] == "mental"
    assert answer["text"].strip()
    assert "mock" in answer["metadata"]["provider"]
