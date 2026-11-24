"""Lightweight retrieval over curated knowledge sources.

Why BM25 first:
  - zero-model startup (no embedding download), instant tests
  - small focused corpora (food facts, training tips) where lexical
    overlap is high — BM25 is competitive and explainable
  - swap-in path: same `Document` + same retriever interface; W4 can
    drop in a dense backend (qdrant-client + fastembed already in deps).

Tokenization:
  - Chinese: jieba.cut_for_search (good recall on short queries)
  - English: simple lowercase split
  - Mixed: tokenize Chinese run via jieba, keep ASCII tokens as-is
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import jieba
from rank_bm25 import BM25Okapi


@dataclass(frozen=True)
class Document:
    """One retrievable chunk."""

    id: str
    text: str
    source: str
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    position: int = 0  # 语料内序号，用于溯源


@dataclass(frozen=True)
class Hit:
    doc: Document
    score: float


_HAN = re.compile(r"[\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """Mixed-language tokenizer: jieba for CJK, lowercase split for ASCII."""
    out: list[str] = []
    pos = 0
    text = text.strip()
    for m in _HAN.finditer(text):
        # ascii before this CJK chunk
        before = text[pos : m.start()]
        if before.strip():
            out.extend(re.findall(r"[a-zA-Z0-9]+", before.lower()))
        han_chunk = m.group(0)
        out.extend(t for t in jieba.cut_for_search(han_chunk) if t.strip())
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        out.extend(re.findall(r"[a-zA-Z0-9]+", tail.lower()))
    return out


class BM25Retriever:
    """In-memory BM25 retriever. Build once, query many times."""

    def __init__(self, docs: Iterable[Document]) -> None:
        self.docs: list[Document] = list(docs)
        if not self.docs:
            raise ValueError("BM25Retriever needs at least one document")
        self._tokens: list[list[str]] = [_tokenize(d.text) for d in self.docs]
        # rank_bm25 doesn't like empty docs; pad just in case
        self._tokens = [t or ["_"] for t in self._tokens]
        self._bm25 = BM25Okapi(self._tokens)

    def search(
        self,
        query: str,
        *,
        k: int = 4,
        tag_filter: str | None = None,
        exclude_tags: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[Hit]:
        """Top-k BM25 search.

        Note on min_score:
          BM25 IDF can be 0 (or negative, clamped to 0 by rank_bm25) when a
          term appears in every doc of a tiny corpus. So we don't apply a
          floor by default. Pass min_score=0.5 (or higher) to enforce one.
        """
        if not query.strip():
            return []
        q_tokens = _tokenize(query) or ["_"]
        scores = self._bm25.get_scores(q_tokens)

        hits: list[Hit] = []
        for doc, score in zip(self.docs, scores):
            if tag_filter is not None and tag_filter not in doc.tags:
                continue
            if exclude_tags and any(t in doc.tags for t in exclude_tags):
                continue
            if min_score is not None and score < min_score:
                continue
            hits.append(Hit(doc=doc, score=float(score)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


def format_citations(hits: list[Hit]) -> list[dict]:
    """Convert hits to a JSON-serializable citations list (for AgentState)."""
    return [
        {
            "id": h.doc.id,
            "source": h.doc.source,
            "position": h.doc.position,
            "tags": list(h.doc.tags),
            "score": round(h.score, 3),
            "quote": h.doc.text,
        }
        for h in hits
    ]
