"""Multi-coach agent state.

This is the contract that flows between Supervisor and Coach nodes.
Each Coach reads from it and returns a partial dict that LangGraph merges in.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


CoachName = Literal["nutrition", "fitness", "data", "end"]


class CoachAnswer(TypedDict, total=False):
    coach: str           # "nutrition" | "fitness" | "data"
    text: str            # human-readable answer
    citations: list[dict]  # [{"id":"food:鸡蛋","quote":"..."}]
    metadata: dict       # tool_calls, latency_ms, ...


class AgentState(TypedDict, total=False):
    # Identity / threading
    user_id: str
    session_id: str
    trace_id: str | None

    # Inputs
    user_message: str
    image_path: str | None
    intent: str            # raw user intent label (set by /chat client or by supervisor)

    # Supervisor decisions
    next_coach: CoachName  # set by supervisor; consumed by router
    handoff_to: str | None # if a coach wants another coach to follow up
    visited_coaches: Annotated[list[str], operator.add]   # cumulative

    # Coach outputs (each coach appends one CoachAnswer)
    coach_answers: Annotated[list[CoachAnswer], operator.add]

    # Final synthesized answer (when supervisor decides to stop)
    final_answer: str
    final_citations: list[dict]
    final_provider: str
    final_model: str
    final_mode: str       # passthrough | primary_addon | safety_first | empty

    # Optional context that any node can populate
    context: dict[str, Any]
