from __future__ import annotations

from langgraph.graph import StateGraph

from lovv_agent_v2.agents.planner.nodes import (
    assemble_itinerary_node,
    retrieve_places_node,
    route_days_node,
)
from lovv_agent_v2.core.state import UnifiedAgentState


def compile_planner_subgraph(checkpointer: object | None = None) -> object:
    workflow = StateGraph(UnifiedAgentState)
    workflow.add_node("retrieve_places", retrieve_places_node)
    workflow.add_node("route_days", route_days_node)
    workflow.add_node("assemble_itinerary", assemble_itinerary_node)
    workflow.set_entry_point("retrieve_places")
    workflow.add_edge("retrieve_places", "route_days")
    workflow.add_edge("route_days", "assemble_itinerary")
    workflow.set_finish_point("assemble_itinerary")
    return workflow.compile(checkpointer=checkpointer)
