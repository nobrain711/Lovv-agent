from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, StateGraph

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.agents.city_select.subgraph import compile_city_select_subgraph
from lovv_agent_v2.agents.festival_verifier.node import festival_verifier_node
from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.agents.planner.steps.weather_alternative.node import weather_alternative_node
from lovv_agent_v2.agents.response_packager.explain_itinerary import explain_itinerary_node
from lovv_agent_v2.agents.response_packager.node import response_packager_node
from lovv_agent_v2.agents.supervisor.router import END_ROUTE, supervisor_node
from lovv_agent_v2.core.state import UnifiedAgentState

GraphNode = Callable[[UnifiedAgentState], Mapping[str, Any]]


def compile_v2_graph(checkpointer: object | None = None) -> object:
    return compile_v2_graph_with_nodes(
        intent_handler=intent_node,
        profile_handler=profile_node,
        checkpointer=checkpointer,
    )


def compile_v2_graph_with_nodes(
    *,
    intent_handler: GraphNode,
    profile_handler: GraphNode,
    checkpointer: object | None = None,
) -> object:
    workflow = StateGraph(UnifiedAgentState)

    workflow.add_node("intent", intent_handler)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("profile", profile_handler)
    workflow.add_node("festival_verifier", festival_verifier_node)
    workflow.add_node("explain_itinerary", explain_itinerary_node)
    workflow.add_node("weather_alternative", weather_alternative_node)
    workflow.add_node("response_packager", response_packager_node)
    city_select_subgraph = compile_city_select_subgraph()
    planner_subgraph = compile_planner_subgraph()
    workflow.add_node("city_select", city_select_subgraph)
    workflow.add_node("planner", planner_subgraph)

    workflow.set_entry_point("intent")
    workflow.add_edge("intent", "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "profile": "profile",
            "festival_verifier": "festival_verifier",
            "city_select": "city_select",
            "planner": "planner",
            "explain_itinerary": "explain_itinerary",
            "weather_alternative": "weather_alternative",
            "response_packager": "response_packager",
            END_ROUTE: END,
        },
    )
    workflow.add_edge("profile", "supervisor")
    workflow.add_edge("festival_verifier", "supervisor")
    workflow.add_edge("city_select", "supervisor")
    workflow.add_edge("planner", "supervisor")
    workflow.add_edge("explain_itinerary", "supervisor")
    workflow.add_edge("weather_alternative", "supervisor")
    workflow.add_edge("response_packager", "supervisor")

    return workflow.compile(checkpointer=checkpointer)


def _route_from_supervisor(state: UnifiedAgentState) -> str:
    routing = state.get("routing", {})
    if not isinstance(routing, dict):
        return END_ROUTE
    next_node = routing.get("next_node")
    return next_node if isinstance(next_node, str) else END_ROUTE

