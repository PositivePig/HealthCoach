"""RAG retriever tests."""

from __future__ import annotations

import pytest

from backend.app.rag import BM25Retriever, Document
from backend.app.rag.retriever import _tokenize, format_citations


def test_tokenize_chinese_only():
    toks = _tokenize("减脂期蛋白质摄入推荐")
    assert "蛋白质" in toks or any("蛋白" in t for t in toks)
    assert any("减脂" in t for t in toks)


def test_tokenize_mixed():
    toks = _tokenize("用 Qwen-VL 识别食物 calories")
    assert "qwen" in toks
    assert "vl" in toks
    assert "calories" in toks
    assert any("识别" in t or "食物" in t for t in toks)


def test_tokenize_empty():
    assert _tokenize("") == []
    assert _tokenize("   ") == []


def test_bm25_retriever_basic():
    docs = [
        Document(id="d1", text="鸡胸肉 高蛋白 低脂肪 减脂", source="t", tags=("protein",)),
        Document(id="d2", text="米饭 主食 碳水", source="t", tags=("carb",)),
        Document(id="d3", text="香蕉 钾 运动后", source="t", tags=("fruit",)),
    ]
    r = BM25Retriever(docs)
    hits = r.search("减脂 高蛋白", k=2)
    assert len(hits) >= 1
    assert hits[0].doc.id == "d1"
    assert hits[0].score > 0


def test_bm25_tag_filter():
    docs = [
        Document(id="a", text="鸡蛋 蛋白质", source="t", tags=("protein",)),
        Document(id="b", text="鸡蛋 早餐", source="t", tags=("breakfast",)),
    ]
    r = BM25Retriever(docs)
    hits = r.search("鸡蛋", k=5, tag_filter="breakfast")
    assert len(hits) == 1
    assert hits[0].doc.id == "b"


def test_bm25_min_score_filter():
    docs = [
        Document(id="x", text="totally unrelated content", source="t"),
    ]
    r = BM25Retriever(docs)
    # Match nothing meaningful → score should be low/zero
    hits = r.search("番茄炒蛋", k=5, min_score=0.5)
    assert hits == []


def test_bm25_empty_corpus_rejected():
    with pytest.raises(ValueError):
        BM25Retriever([])


def test_bm25_empty_query_returns_empty():
    docs = [Document(id="d", text="anything", source="t")]
    r = BM25Retriever(docs)
    assert r.search("") == []
    assert r.search("   ") == []


def test_format_citations_includes_source_metadata():
    doc = Document(
        id="food:鸡蛋",
        text="鸡蛋每100g约144 kcal",
        source="中国食物成分表",
        tags=("food", "protein"),
        position=3,
    )
    r = BM25Retriever([doc])
    hits = r.search("鸡蛋", k=1)
    citations = format_citations(hits)

    assert citations[0]["id"] == "food:鸡蛋"
    assert citations[0]["source"] == "中国食物成分表"
    assert citations[0]["position"] == 3
    assert "鸡蛋" in citations[0]["quote"]


# ---------- against the real seed corpus ----------


def test_seed_corpus_recall_for_typical_questions():
    """Smoke: BM25 should hit at least one relevant doc in top-5 for representative questions.

    BM25 favors lexical density, so e.g. a query about减脂蛋白 may surface
    high-protein食物条目 before the principle doc. We accept either, since
    both are useful for the coach.
    """
    from backend.app.rag.seeds.nutrition_seed import build_nutrition_corpus
    r = BM25Retriever(build_nutrition_corpus())

    cases = [
        # query, set of acceptable doc ids
        (
            "我目标减脂，蛋白质要吃多少？",
            {"principle:protein_target_cut",
             "principle:protein_target_general",
             "food:鸡胸肉", "food:鸡蛋", "food:豆腐"},
        ),
        (
            "跑完 5 公里之后该补什么？",
            {"principle:post_workout_carb_protein", "food:香蕉"},
        ),
        ("三文鱼有什么营养？", {"food:三文鱼"}),
        (
            "每天纤维要多少",
            {"principle:fiber_target", "food:燕麦", "food:绿叶蔬菜"},
        ),
    ]
    for query, ok_set in cases:
        hits = r.search(query, k=5)
        ids = [h.doc.id for h in hits]
        overlap = set(ids) & ok_set
        assert overlap, (
            f"query={query!r} expected any of {ok_set} in top-5, got {ids}"
        )
