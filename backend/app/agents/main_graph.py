"""Main multi-coach LangGraph (W4 D2).

Flow:
                ┌─→ nutrition ─┐
                ├─→ fitness  ─┤
   START ─→ supervisor ─┼─→ mental   ─┼─→ supervisor ─→ ... ─→ finalize ─→ END
                └─→ data     ─┘

D1 added mental coach (with crisis/redline detection).
D2 replaces data placeholder with real data_analyst_node.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes.data_analyst import data_analyst_node
from .nodes.fitness_coach import fitness_coach_node
from .nodes.mental_coach import mental_coach_node
from .nodes.nutrition_coach import nutrition_coach_node
from .state import AgentState, CoachAnswer
from .supervisor import finalize_node, supervisor_node


# ---------- graph build ----------


def build_main_graph() -> Any:
    g: StateGraph = StateGraph(AgentState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("nutrition", nutrition_coach_node)
    g.add_node("fitness", fitness_coach_node)
    g.add_node("mental", mental_coach_node)
    g.add_node("data", data_analyst_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "supervisor")
    # all coach nodes return Command(goto="supervisor")
    g.add_edge("data", "supervisor")
    g.add_edge("finalize", END)
    return g.compile()


_compiled = None


def get_main_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_main_graph()
    return _compiled
