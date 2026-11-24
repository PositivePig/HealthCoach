"""Semantic Memory Store (Qdrant-backed).

Stores long-term user facts as vector embeddings for semantic retrieval.

Uses:
  - Qdrant (embedded mode for dev, server mode for prod)
  - fastembed for text embeddings (already in dependencies)

Design:
  - One collection per user: `{user_id}_facts`
    (Isolated, easy to delete, but more collections)
  - Alternative: one shared collection with `user_id` payload filter
    (Fewer collections, but cross-user contamination risk is zero due to filter)
  - We choose **one shared collection** with payload filter for simplicity.
    Collection name: `healthcoach_facts`
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)
from qdrant_client.http.models import CollectionStatus

from ..core.config import get_settings
from ..core.logging import get_logger
from ..memory.types import Fact, FactSearchResult, FactTag

log = get_logger(__name__)

COLLECTION_NAME = "healthcoach_facts"
VECTOR_SIZE = 384  # fastembed default (all-MiniLM-L6-v2)
TIMEESTAMP_KEY = "created_at"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_point_id(fact_id: str) -> str:
    """Creates a deterministic point ID from a fact ID.

    Qdrant needs a string ID; we hash the fact_id to ensure determinism.
    """
    return hashlib.sha256(fact_id.encode()).hexdigest()[:32]


def _fact_to_payload(fact: Fact) -> dict[str, Any]:
    """Convert a Fact to Qdrant payload."""
    return {
        "fact_id": fact.id or "",
        "user_id": fact.user_id,
        "fact_text": fact.fact,
        "tags": [t.value for t in fact.tags] if fact.tags else [],
        "confidence": fact.confidence,
        "source": fact.source,
        "current": fact.current,
        "created_at": fact.created_at.isoformat() if fact.created_at else "",
        "updated_at": fact.updated_at.isoformat() if fact.updated_at else "",
    }


def _payload_to_fact(
    payload: dict[str, Any],
    score: float | None = None,
) -> Fact:
    """Convert Qdrant payload (+ optional score) back to Fact."""
    tags = []
    for t in payload.get("tags", []):
        try:
            tags.append(FactTag(t))
        except ValueError:
            pass

    created_str = payload.get("created_at", "")
    updated_str = payload.get("updated_at", "")

    return Fact(
        id=payload.get("fact_id") or None,
        user_id=payload["user_id"],
        fact=payload["fact_text"],
        tags=tags,
        confidence=payload.get("confidence", 1.0),
        source=payload.get("source", "user"),
        current=payload.get("current", True),
        created_at=datetime.fromisoformat(created_str) if created_str else None,
        updated_at=datetime.fromisoformat(updated_str) if updated_str else None,
    )


# ---------------------------------------------------------------------------
# SemanticStore
# ---------------------------------------------------------------------------


class SemanticStore:
    """Vector-backed semantic memory store (Qdrant).

    Automatically chooses between:
    - Embedded mode (local file storage, no Docker needed) for SQLite backend
    - Remote mode (HTTP client to Qdrant server) for Postgres backend
    """

    def __init__(self) -> None:
        settings = get_settings()

        # Choose Qdrant mode based on storage backend (ADR-0006)
        if settings.storage_backend == "sqlite":
            # Embedded mode: stores data in ./data/qdrant/
            import os
            qdrant_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "qdrant")
            os.makedirs(qdrant_path, exist_ok=True)
            self.client = QdrantClient(path=qdrant_path)
            log.info("qdrant_embedded_mode", path=qdrant_path)
        else:
            # Remote mode: connect to Qdrant server
            self.client = QdrantClient(
                url=settings.qdrant_url,
                prefer_grpc=False,
            )
            log.info("qdrant_remote_mode", url=settings.qdrant_url)

        self.collection = COLLECTION_NAME
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        try:
            info = self.client.get_collection(self.collection)
            if info.status == CollectionStatus.GREEN:
                log.info("qdrant_collection_exists", name=self.collection)
                return
        except Exception:
            pass

        # Create collection
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )

        # Create payload indexes for faster filtering
        self.client.create_payload_index(
            collection_name=self.collection,
            field_name="user_id",
            field_schema="keyword",
        )
        self.client.create_payload_index(
            collection_name=self.collection,
            field_name="tags",
            field_schema="keyword",
        )
        self.client.create_payload_index(
            collection_name=self.collection,
            field_name="current",
            field_schema="bool",
        )
        log.info("qdrant_collection_created", name=self.collection)

    # -- write ---------------------------------------------------------------

    async def add_fact(
        self,
        fact: Fact,
    ) -> str:
        """Add a fact to semantic memory.

        Returns the fact ID.
        """
        if fact.id is None:
            fact.id = f"fact_{uuid.uuid4().hex[:12]}"

        point_id = _make_point_id(fact.id)
        payload = _fact_to_payload(fact)

        # Generate embedding from fact text
        embedding_model = TextEmbedding()
        raw_vectors = list(embedding_model.passage_embed([fact.fact]))
        # raw_vectors: List[np.ndarray]; convert to plain list
        vector = list(raw_vectors[0]) if hasattr(raw_vectors[0], "tolist") else list(raw_vectors[0])

        self.client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )

        log.info("semantic_fact_added", user_id=fact.user_id, fact_id=fact.id)
        return fact.id

    async def add_facts(
        self,
        facts: list[Fact],
    ) -> list[str]:
        """Batch add facts. Returns list of fact IDs."""
        ids = []
        for f in facts:
            fid = await self.add_fact(f)
            ids.append(fid)
        return ids

    async def update_fact(
        self,
        fact: Fact,
    ) -> None:
        """Update an existing fact (upsert)."""
        if fact.id is None:
            raise ValueError("Cannot update fact without ID")
        await self.add_fact(fact)  # upsert

    async def remove_fact(
        self,
        user_id: str,
        fact_id: str,
    ) -> bool:
        """Remove a fact by ID. Returns True if removed."""
        point_id = _make_point_id(fact_id)

        # Verify ownership
        points = self.client.retrieve(
            collection_name=self.collection,
            ids=[point_id],
        )
        if not points:
            return False
        if points[0].payload.get("user_id") != user_id:
            log.warning(
                "semantic_fact_delete_denied",
                user_id=user_id,
                fact_id=fact_id,
            )
            return False

        self.client.delete(
            collection_name=self.collection,
            points_selector=[point_id],
        )
        log.info("semantic_fact_removed", user_id=user_id, fact_id=fact_id)
        return True

    # -- read ---------------------------------------------------------------

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        k: int = 5,
        tags: list[FactTag] | None = None,
        min_confidence: float = 0.0,
        current_only: bool = True,
    ) -> list[FactSearchResult]:
        """Semantic search over user's facts.

        Args:
            user_id: Which user's facts to search.
            query: Natural language query.
            k: Max number of results.
            tags: Optional tag filter.
            min_confidence: Minimum confidence threshold.
            current_only: Only return facts with current=True.
        """
        # Build filter
        filter_conditions = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        ]
        if current_only:
            filter_conditions.append(
                FieldCondition(key="current", match=MatchValue(value=True)),
            )
        if tags:
            filter_conditions.append(
                FieldCondition(key="tags", match=MatchValue(value=[t.value for t in tags])),
            )
        if min_confidence > 0:
            filter_conditions.append(
                Range(key="confidence", gte=min_confidence),
            )

        query_filter = Filter(must=filter_conditions) if filter_conditions else None

        # Generate query embedding
        embedding_model = TextEmbedding()
        raw_vectors = list(embedding_model.embed([query]))  # 使用通用embed方法
        query_vector = list(raw_vectors[0]) if hasattr(raw_vectors[0], "tolist") else list(raw_vectors[0])

        # 使用 query_points (qdrant-client v1.x API)
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=k,
        )
        
        # query_points 返回 QueryResponse，包含 .points 属性
        results = response.points if hasattr(response, "points") else response

        return [
            FactSearchResult(
                fact=_payload_to_fact(hit.payload, hit.score),
                score=hit.score,
            )
            for hit in results
        ]

    async def list_by_tag(
        self,
        user_id: str,
        tag: FactTag | str,
        *,
        current_only: bool = True,
    ) -> list[Fact]:
        """List all facts with a given tag (non-semantic, exact match)."""
        tag_value = tag.value if isinstance(tag, FactTag) else tag
        filter_conditions = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="tags", match=MatchValue(value=tag_value)),
        ]
        if current_only:
            filter_conditions.append(
                FieldCondition(key="current", match=MatchValue(value=True)),
            )

        points = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=filter_conditions),
            limit=100,
        )[0]

        return [_payload_to_fact(p.payload) for p in points]

    async def get_profile(self, user_id: str) -> list[Fact]:
        """Shortcut: get all profile facts for a user."""
        return await self.list_by_tag(user_id, FactTag.PROFILE, current_only=True)

    async def get_all_for_user(
        self,
        user_id: str,
        *,
        current_only: bool = False,
    ) -> list[Fact]:
        """Get ALL facts for a user (no semantic search)."""
        filter_conditions = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        ]
        if current_only:
            filter_conditions.append(
                FieldCondition(key="current", match=MatchValue(value=True)),
            )

        points = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(must=filter_conditions) if filter_conditions else None,
            limit=500,
        )[0]

        return [_payload_to_fact(p.payload) for p in points]

    async def remove_all_for_user(self, user_id: str) -> int:
        """Remove ALL semantic facts for a user (GDPR-style delete).

        Returns the number of facts removed.
        """
        points = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))],
            ),
            limit=1000,
            with_payload=False,
            with_vectors=False,
        )[0]

        if not points:
            return 0

        point_ids = [p.id for p in points]
        self.client.delete(
            collection_name=self.collection,
            points_selector=point_ids,
        )

        log.info(
            "semantic_facts_deleted_all", user_id=user_id, count=len(point_ids)
        )
        return len(point_ids)

    # -- conflict detection ---------------------------------------------------

    async def detect_conflicts(
        self,
        user_id: str,
        new_fact: str,
        *,
        similarity_threshold: float = 0.8,
    ) -> list[Fact]:
        """Detect if new_fact conflicts with existing facts.

        Returns potentially conflicting facts (high semantic similarity
        but potentially contradictory).

        Note: This is a heuristic. True conflict detection needs LLM.
        """
        results = await self.search(
            user_id, new_fact, k=3, current_only=True
        )

        # Filter by similarity threshold
        conflicts = [
            r.fact for r in results if r.score >= similarity_threshold
        ]

        # TODO (W5): Use LLM to verify actual contradiction
        return conflicts
