"""Compile 2-node City Selection Subgraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.agents.city_select.retrieval_node import retrieval_node
from lovv_agent_v2.agents.city_select.scoring_and_selection_node import scoring_and_selection_node


def compile_city_select_subgraph(checkpointer: Any | None = None) -> Any:
    """Build and compile the 2-node city selection subgraph."""

    builder = StateGraph(UnifiedAgentState)

    # 1. 노드 등록
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("scoring_and_selection", scoring_and_selection_node)

    # 2. 엣지 연결 (retrieval -> scoring_and_selection)
    builder.set_entry_point("retrieval")
    builder.add_edge("retrieval", "scoring_and_selection")
    builder.set_finish_point("scoring_and_selection")

    return builder.compile(checkpointer=checkpointer)


__all__ = ["compile_city_select_subgraph"]
