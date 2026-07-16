from __future__ import annotations

from langgraph.graph import END, StateGraph

from lovv_agent_v2.agents.planner.state_adapter import (
    assemble_itinerary_step,
    retrieve_places,
    retry_alternative_city,
    route_days_step,
)
from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node
from lovv_agent_v2.agents.planner.steps.retry_alternative_city.node import (
    should_retry_alternative_city,
)
from lovv_agent_v2.agents.planner.steps.weather_alternative.node import (
    weather_alternative_node,
)
from lovv_agent_v2.common.telemetry import trace_node
from lovv_agent_v2.core.state import UnifiedAgentState


def compile_planner_subgraph(checkpointer: object | None = None) -> object:
    workflow = StateGraph(UnifiedAgentState)
    workflow.add_node("retrieve_places", trace_node("planner.retrieve_places", retrieve_places))
    workflow.add_node("apply_edit", trace_node("planner.apply_edit", apply_edit_node))
    workflow.add_node("route_days", trace_node("planner.route_days", route_days_step))
    workflow.add_node(
        "assemble_itinerary",
        trace_node("planner.assemble_itinerary", assemble_itinerary_step),
    )
    workflow.add_node(
        "retry_alternative_city",
        trace_node("planner.retry_alternative_city", retry_alternative_city),
    )
    workflow.add_node(
        "weather_alternative",
        trace_node("planner.weather_alternative", weather_alternative_node),
    )
    workflow.set_conditional_entry_point(
        _entry_point,
        {"apply_edit": "apply_edit", "retrieve_places": "retrieve_places"},
    )
    workflow.add_edge("retrieve_places", "route_days")
    workflow.add_edge("apply_edit", "weather_alternative")
    workflow.add_edge("route_days", "assemble_itinerary")
    workflow.add_conditional_edges(
        "assemble_itinerary",
        _route_after_assemble,
        {
            "retry_alternative_city": "retry_alternative_city",
            "weather_alternative": "weather_alternative",
        },
    )
    workflow.add_edge("retry_alternative_city", "retrieve_places")
    workflow.add_edge("weather_alternative", END)
    return workflow.compile(checkpointer=checkpointer)


def _route_after_assemble(state: UnifiedAgentState) -> str:
    if should_retry_alternative_city(state):
        return "retry_alternative_city"
    return "weather_alternative"


def _entry_point(state: UnifiedAgentState) -> str:
    intent = state.get("intent", {})
    if not isinstance(intent, dict):
        return "retrieve_places"
    modify_intent = intent.get("modify_intent")
    if not isinstance(modify_intent, dict):
        return "retrieve_places"
    if (
        modify_intent.get("status") == "ok"
        and modify_intent.get("kind") in {"slot_replace", "day_regenerate"}
        and modify_intent.get("routing_hint") == "planner_apply_edit"
    ):
        return "apply_edit"
    return "retrieve_places"
