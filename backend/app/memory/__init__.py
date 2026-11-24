"""Three-layer memory system for HealthCoachAgent.

Imports:
  - types: Type definitions (EpisodicEvent, Fact, ProceduralProfile, etc.)
  - episodic: EpisodicStore (event retrieval)
  - semantic: SemanticStore (vector retrieval, Qdrant-backed)
  - procedural: ProceduralStore (KV preferences)
  - get_memory_context: Helper to bundle all three for agent prompts
"""

from __future__ import annotations

from .episodic import EpisodicStore
from .procedural import ProceduralStore
from .semantic import SemanticStore
from .types import (
    CommunicationStyle,
    DetailLevel,
    EpisodicEvent,
    EventKind,
    Fact,
    FactSearchResult,
    FactTag,
    ProceduralProfile,
)

__all__ = [
    # Stores
    "EpisodicStore",
    "SemanticStore",
    "ProceduralStore",
    # Types
    "EpisodicEvent",
    "EventKind",
    "Fact",
    "FactSearchResult",
    "FactTag",
    "ProceduralProfile",
    "CommunicationStyle",
    "DetailLevel",
]


async def get_memory_context(
    user_id: str,
    session: "AsyncSession",
    query: str | None = None,
    *,
    episodic_days: int = 7,
    semantic_k: int = 5,
) -> "MemoryContext":
    """Convenience: fetch all three memory layers at once.

    Args:
        user_id: User to fetch memory for.
        session: SQLAlchemy async session.
        query: Optional query string for semantic search.
        episodic_days: How many days of episodic events to fetch.
        semantic_k: How many semantic facts to retrieve.

    Returns:
        MemoryContext with all three layers populated.
    """
    from .types import MemoryContext

    # 1. Procedural (communication style)
    proc_store = ProceduralStore(session)
    procedural = await proc_store.get(user_id)

    # 2. Semantic (user profile + query-relevant facts) - gracefully handle Qdrant unavailable
    semantic_profile: list[str] = []
    semantic_relevant: list[Fact] = []
    try:
        sem_store = SemanticStore()
        semantic_profile = await sem_store.get_profile(user_id)
        if query:
            results = await sem_store.search(user_id, query, k=semantic_k)
            semantic_relevant = [r.fact for r in results]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"SemanticStore unavailable (Qdrant not running?): {e}")
        # Continue with empty semantic data

    # 3. Episodic (recent events)
    epi_store = EpisodicStore(session)
    episodic_data = await epi_store.query_all(
        user_id, days=episodic_days, include_unstructured=True
    )

    # Flatten into EpisodicEvent list
    from .types import EpisodicEvent as EpisodicEventModel

    episodic_events: list[EpisodicEventModel] = []

    for meal in episodic_data.get("meals", []):
        episodic_events.append(
            EpisodicEventModel(
                user_id=user_id,
                kind=EventKind.MEAL,
                ts=meal["ts"],
                payload=meal,
            )
        )

    for act in episodic_data.get("activities", []):
        episodic_events.append(
            EpisodicEventModel(
                user_id=user_id,
                kind=EventKind.ACTIVITY,
                ts=act["ts"],
                payload=act,
            )
        )

    # Sort by ts descending
    episodic_events.sort(key=lambda e: e.ts, reverse=True)
    episodic_events = episodic_events[:50]  # cap at 50

    return MemoryContext(
        procedural=procedural,
        semantic_profile=semantic_profile,
        semantic_relevant=semantic_relevant,
        episodic_recent=episodic_events,
    )
