"""Main Graph definition and routing compilation."""

from __future__ import annotations

from langgraph.graph import StateGraph

from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.city_select.subgraph import compile_city_select_subgraph
from lovv_agent_v2.agents.festival_verifier.node import festival_verifier_node
from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.agents.response_packager.explain_itinerary import explain_itinerary_node
from lovv_agent_v2.agents.response_packager.node import response_packager_node
from lovv_agent_v2.core.state import UnifiedAgentState


def compile_v2_graph(checkpointer: object | None = None) -> object:
    """Build and compile the main LangGraph for V2."""

    workflow = StateGraph(UnifiedAgentState)

    workflow.add_node("intent", intent_node)
    workflow.add_node("profile", profile_node)
    workflow.add_node("festival_verifier", festival_verifier_node)
    workflow.add_node("explain_itinerary", explain_itinerary_node)
    workflow.add_node("response_packager", response_packager_node)
    city_select_subgraph = compile_city_select_subgraph(checkpointer=checkpointer)
    planner_subgraph = compile_planner_subgraph(checkpointer=checkpointer)
    workflow.add_node("city_select", city_select_subgraph)
    workflow.add_node("planner", planner_subgraph)

    workflow.set_entry_point("intent")
    workflow.add_edge("intent", "profile")
    workflow.add_edge("profile", "festival_verifier")
    workflow.add_conditional_edges(
        "festival_verifier",
        _route_after_festival_gate,
        {"city_select": "city_select", "response_packager": "response_packager"},
    )
    workflow.add_edge("city_select", "planner")
    workflow.add_edge("planner", "explain_itinerary")
    workflow.add_edge("explain_itinerary", "response_packager")
    workflow.set_finish_point("response_packager")

    return workflow.compile(checkpointer=checkpointer)


def _route_after_festival_gate(state: UnifiedAgentState) -> str:
    routing = state.get("routing", {})
    if isinstance(routing, dict) and routing.get("needs_clarification") is True:
        return "response_packager"
    return "city_select"

