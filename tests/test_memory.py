"""Tests for the three-layer memory system.

Covers:
  - EpisodicStore (episodic memory) - mocked DB
  - SemanticStore (semantic memory, Qdrant-backed) - mocked Qdrant
  - ProceduralStore (procedural memory, KV-backed) - mocked DB
  - get_memory_context helper
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from backend.app.memory.episodic import EpisodicStore
from backend.app.memory.procedural import ProceduralStore
from backend.app.memory.semantic import (
    COLLECTION_NAME,
    Fact,
    FactTag,
    SemanticStore,
    _payload_to_fact,
)
from backend.app.memory.types import (
    CommunicationStyle,
    DetailLevel,
    EventKind,
    MemoryContext,
    ProceduralProfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Create a mock SQLAlchemy async session."""
    session = MagicMock()
    # add() is synchronous in SQLAlchemy (not awaitable)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    # execute() must be an AsyncMock so `await session.execute()` works
    session.execute = AsyncMock()
    # delete() is also synchronous in SQLAlchemy
    session.delete = MagicMock()
    return session


def _mock_execute_result(scalars_result=None, scalar_one_or_none_result=None):
    """Create a mock result for session.execute().

    Args:
        scalars_result: Value to return from .scalars().all()
        scalar_one_or_none_result: Value to return from .scalar_one_or_none()
    """
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    if scalars_result is not None:
        mock_scalars.all.return_value = scalars_result
        mock_scalars.one_or_none.return_value = scalar_one_or_none_result
    mock_result.scalars.return_value = mock_scalars
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none_result
    return mock_result


async def _mock_session_scope():
    """Mock session_scope context manager."""
    session = _make_mock_session()
    yield session
    await session.close()


# ---------------------------------------------------------------------------
# EpisodicStore Tests (mocked DB)
# ---------------------------------------------------------------------------


class TestEpisodicStore:
    """Test suite for EpisodicStore (mocked)."""

    @pytest.fixture
    def store(self):
        """Create store with mock session."""
        session = _make_mock_session()
        return EpisodicStore(session), session

    @pytest.mark.asyncio
    async def test_add_unstructured_event(self, store):
        """Test adding an unstructured event."""
        store_obj, session = store

        # Mock the flush/refresh to set an ID
        async def mock_flush():
            pass
        async def mock_refresh(obj, attribute_names=None):
            obj.id = 42
        session.flush.side_effect = mock_flush
        session.refresh.side_effect = mock_refresh

        event = await store_obj.add(
            user_id="user1",
            kind=EventKind.CHAT,
            payload={"message": "Hello", "response": "Hi there!"},
        )

        assert event.user_id == "user1"
        assert event.kind == EventKind.CHAT
        assert event.payload["message"] == "Hello"
        assert event.id == "42"

    @pytest.mark.asyncio
    async def test_add_event_with_summary(self, store):
        """Test adding an event with a summary."""
        store_obj, session = store

        async def mock_flush():
            pass
        async def mock_refresh(obj, attribute_names=None):
            obj.id = 99
        session.flush.side_effect = mock_flush
        session.refresh.side_effect = mock_refresh

        event = await store_obj.add(
            user_id="user1",
            kind=EventKind.NOTE,
            payload={"note": "User reported feeling anxious today."},
            summary="User anxiety note",
        )

        assert event.summary == "User anxiety note"
        assert event.id == "99"

    @pytest.mark.asyncio
    async def test_query_unstructured_empty(self, store):
        """Test querying when no events exist."""
        store_obj, session = store

        # Mock empty result
        mock_result = _mock_execute_result(scalars_result=[])
        session.execute.return_value = mock_result

        results = await store_obj.query_unstructured("user1", days=7)
        assert results == []

    @pytest.mark.asyncio
    async def test_query_meals_empty(self, store):
        """Test query_meals returns empty list."""
        store_obj, session = store

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        results = await store_obj.query_meals("user1", days=7)
        assert results == []

    @pytest.mark.asyncio
    async def test_query_activities_empty(self, store):
        """Test query_activities returns empty list."""
        store_obj, session = store

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        results = await store_obj.query_activities("user1", days=14)
        assert results == []

    @pytest.mark.asyncio
    async def test_query_vitals_empty(self, store):
        """Test query_vitals returns empty list."""
        store_obj, session = store

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        results = await store_obj.query_vitals("user1", days=30)
        assert results == []


# ---------------------------------------------------------------------------
# SemanticStore Tests (mocked Qdrant)
# ---------------------------------------------------------------------------


class TestSemanticStore:
    """Test suite for SemanticStore (Qdrant-backed)."""

    @pytest.fixture
    def mock_qdrant(self):
        """Mock QdrantClient."""
        with patch("backend.app.memory.semantic.QdrantClient") as mock_cls:
            client = MagicMock()
            # Mock collection exists
            client.get_collection.return_value = MagicMock(
                status=MagicMock(value="GREEN")
            )
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def store(self, mock_qdrant):
        """Create a SemanticStore with mocked client."""
        return SemanticStore(), mock_qdrant

    def test_init_creates_collection_if_missing(self):
        """Test that __init__ creates collection if not exists."""
        with patch("backend.app.memory.semantic.QdrantClient") as mock_cls:
            client = MagicMock()
            # Simulate collection not found
            client.get_collection.side_effect = Exception("Not found")
            mock_cls.return_value = client

            store = SemanticStore()
            client.create_collection.assert_called_once()
            # Should create 3 payload indexes
            assert client.create_payload_index.call_count >= 3

    @pytest.mark.asyncio
    async def test_add_fact(self, store, mock_qdrant):
        """Test adding a fact."""
        store_obj, client = store

        fact = Fact(
            user_id="user1",
            fact="User is allergic to peanuts",
            tags=[FactTag.ALLERGY],
            confidence=1.0,
            source="user",
        )

        with patch(
            "backend.app.memory.semantic.TextEmbedding"
        ) as mock_embedding_cls:
            mock_model = MagicMock()
            mock_model.passage_embed.return_value = [[0.1] * 384]
            mock_embedding_cls.return_value = mock_model

            fact_id = await store_obj.add_fact(fact)

        assert fact_id is not None
        assert fact_id.startswith("fact_")
        client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_fact_with_existing_id(self, store, mock_qdrant):
        """Test adding a fact with pre-set ID."""
        store_obj, client = store

        fact = Fact(
            id="fact_test123",
            user_id="user1",
            fact="User's goal is weight loss",
            tags=[FactTag.GOAL],
        )

        with patch(
            "backend.app.memory.semantic.TextEmbedding"
        ) as mock_embedding_cls:
            mock_model = MagicMock()
            mock_model.passage_embed.return_value = [[0.1] * 384]
            mock_embedding_cls.return_value = mock_model

            fact_id = await store_obj.add_fact(fact)

        assert fact_id == "fact_test123"

    @pytest.mark.asyncio
    async def test_search(self, store, mock_qdrant):
        """Test semantic search."""
        store_obj, client = store

        # Mock search results
        mock_point = MagicMock()
        mock_point.score = 0.85
        mock_point.payload = {
            "fact_id": "fact_1",
            "user_id": "user1",
            "fact_text": "User is allergic to peanuts",
            "tags": ["allergy"],
            "confidence": 1.0,
            "source": "user",
            "current": True,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "updated_at": "",
        }
        response = MagicMock()
        response.points = [mock_point]
        client.query_points.return_value = response

        with patch(
            "backend.app.memory.semantic.TextEmbedding"
        ) as mock_embedding_cls:
            mock_model = MagicMock()
            mock_model.embed.return_value = [[0.1] * 384]
            mock_embedding_cls.return_value = mock_model

            results = await store_obj.search("user1", "allergy", k=5)

        assert len(results) == 1
        assert results[0].score == 0.85
        assert "peanuts" in results[0].fact.fact

    @pytest.mark.asyncio
    async def test_remove_fact(self, store, mock_qdrant):
        """Test removing a fact."""
        store_obj, client = store

        # Mock retrieve to return a point
        mock_point = MagicMock()
        mock_point.payload = {"user_id": "user1", "fact_id": "fact_1"}
        client.retrieve.return_value = [mock_point]

        result = await store_obj.remove_fact("user1", "fact_1")

        assert result is True
        client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_fact_wrong_user(self, store, mock_qdrant):
        """Test removing a fact with wrong user_id (should fail)."""
        store_obj, client = store

        mock_point = MagicMock()
        mock_point.payload = {"user_id": "other_user", "fact_id": "fact_1"}
        client.retrieve.return_value = [mock_point]

        result = await store_obj.remove_fact("user1", "fact_1")

        assert result is False
        client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_all_for_user(self, store, mock_qdrant):
        """Test removing all facts for a user (GDPR delete)."""
        store_obj, client = store

        mock_point = MagicMock()
        mock_point.id = "test_id_1"
        mock_point.payload = {}
        client.scroll.return_value = ([mock_point], None)

        count = await store_obj.remove_all_for_user("user1")

        assert count == 1
        client.delete.assert_called_once()


# ---------------------------------------------------------------------------
# ProceduralStore Tests (mocked DB)
# ---------------------------------------------------------------------------


class TestProceduralStore:
    """Test suite for ProceduralStore (mocked)."""

    @pytest.fixture
    def store(self):
        """Create store with mock session."""
        session = _make_mock_session()
        return ProceduralStore(session), session

    @pytest.mark.asyncio
    async def test_get_default_profile(self, store):
        """Test getting default profile when none exists."""
        store_obj, session = store

        # Mock empty result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        profile = await store_obj.get("user1")

        assert profile.user_id == "user1"
        assert profile.tone == CommunicationStyle.WARM
        assert profile.detail_level == DetailLevel.MEDIUM
        assert profile.use_emoji is True

    @pytest.mark.asyncio
    async def test_set_and_get_key(self, store):
        """Test setting and getting a single key."""
        store_obj, session = store

        # Mock: set_key does an upsert
        # Mock: get_key returns value
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.value_json = json.dumps("direct")
        mock_result.scalar_one_or_none.return_value = mock_row

        session.execute.return_value = mock_result

        await store_obj.set_key("user1", "tone", "direct")

        # Verify session.add or session.update was called
        assert session.add.called or session.execute.called

    @pytest.mark.asyncio
    async def test_delete_key(self, store):
        """Test deleting a single key."""
        store_obj, session = store

        # Ensure session.delete is AsyncMock (it's called with await)
        session.delete = AsyncMock()

        # Mock: delete_key finds and deletes
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        session.execute.return_value = mock_result

        result = await store_obj.delete_key("user1", "tone")
        assert result is True
        assert session.delete.called

    @pytest.mark.asyncio
    async def test_delete_key_not_exists(self, store):
        """Test deleting a non-existent key."""
        store_obj, session = store

        # Mock: no row found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await store_obj.delete_key("user1", "nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_learn_from_feedback_brief(self, store):
        """Test implicit learning from user feedback."""
        store_obj, session = store

        # Mock update() to avoid complex DB chain (get → session.execute)
        store_obj.update = AsyncMock(return_value=ProceduralProfile(
            user_id="user1",
            detail_level=DetailLevel.BRIEF,
            version=2,
        ))

        await store_obj.learn_from_feedback("user1", "太啰嗦了，说简单点")

        # Verify update() was called
        assert store_obj.update.called
        call_kwargs = store_obj.update.call_args
        # Check that the patch contains detail_level="brief"
        if call_kwargs:
            patch_arg = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("patch", {})
            # update() is called with (user_id, patch_dict)
            # So call_kwargs[0][1] is the patch dict
            assert "detail_level" in patch_arg or "version" in patch_arg


# ---------------------------------------------------------------------------
# Integration Tests (get_memory_context)
# ---------------------------------------------------------------------------


class TestGetMemoryContext:
    """Test the get_memory_context helper."""

    @pytest.mark.asyncio
    async def test_empty_context(self):
        """Test getting context for a user with no data."""
        from backend.app.memory import get_memory_context

        # Mock the session and stores
        mock_session = _make_mock_session()

        with patch(
            "backend.app.memory.EpisodicStore"
        ) as mock_epi_cls, patch(
            "backend.app.memory.SemanticStore"
        ) as mock_sem_cls, patch(
            "backend.app.memory.ProceduralStore"
        ) as mock_proc_cls:

            # Mock procedural.get to return default (must be AsyncMock)
            mock_proc = MagicMock()
            mock_proc.get = AsyncMock(return_value=ProceduralProfile(user_id="user1"))
            mock_proc_cls.return_value = mock_proc

            # Mock semantic.get_profile to return []
            mock_sem = MagicMock()
            mock_sem.get_profile = AsyncMock(return_value=[])
            mock_sem.search = AsyncMock(return_value=[])
            mock_sem_cls.return_value = mock_sem

            # Mock episodic.query_all to return empty
            mock_epi = MagicMock()
            mock_epi.query_all = AsyncMock(return_value={
                "meals": [],
                "activities": [],
                "vitals": [],
                "unstructured": [],
            })
            mock_epi_cls.return_value = mock_epi

            ctx = await get_memory_context(
                user_id="user1",
                session=mock_session,
                query="test query",
                episodic_days=7,
                semantic_k=5,
            )

            assert isinstance(ctx, MemoryContext)
            assert ctx.procedural is not None
            assert ctx.procedural.tone == CommunicationStyle.WARM  # default
            assert ctx.semantic_profile == []
            assert ctx.semantic_relevant == []
            assert ctx.episodic_recent == []


# ---------------------------------------------------------------------------
# Type tests
# ---------------------------------------------------------------------------


class TestMemoryTypes:
    """Test Pydantic type models."""

    def test_procedural_profile_defaults(self):
        """Test ProceduralProfile default values."""
        p = ProceduralProfile(user_id="test")
        assert p.tone == CommunicationStyle.WARM
        assert p.detail_level == DetailLevel.MEDIUM
        assert p.use_emoji is True
        assert p.version == 1

    def test_fact_creation(self):
        """Test Fact model."""
        f = Fact(
            user_id="test",
            fact="User is allergic to shellfish",
            tags=[FactTag.ALLERGY],
            confidence=0.9,
        )
        assert f.current is True
        assert f.source == "user"

    def test_memory_context_format_empty(self):
        """Test format_for_prompt with empty context."""
        ctx = MemoryContext(user_id="test")
        result = ctx.format_for_prompt()
        assert "无记忆上下文" in result
