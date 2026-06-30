from __future__ import annotations

from collections.abc import Mapping

from lovv_agent_v2.agents.planner.nodes import (
    assemble_itinerary_node,
    retrieve_places_node,
    route_days_node,
)
from lovv_agent_v2.core.state import UnifiedAgentState


def planner_node(state: UnifiedAgentState) -> dict[str, object]:
    if not isinstance(state.get("city_select"), Mapping):
        return {
            "planner": {
                "planner_output": None,
                "validation_result": {"planner_status_gate": "no_city_selection"},
                "audit": {},
            },
        }
    retrieved = retrieve_places_node(state)
    route_state = {**state, **retrieved}
    routed = route_days_node(route_state)
    assemble_state = {**route_state, **routed}
    return assemble_itinerary_node(assemble_state)
