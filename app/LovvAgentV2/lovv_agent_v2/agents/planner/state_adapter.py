from __future__ import annotations

from collections.abc import Mapping

from lovv_agent_v2.agents.planner.agent import PlannerAgent, PlannerAgentRequest, PlannerAgentTools
from lovv_agent_v2.agents.planner.state.context import (
    fallback_places,
    int_value,
    mapping,
    mapping_sequence,
    optional_text,
    planner_input,
    runtime_tools,
    string_tuple,
    text,
    theme_weights,
    travel_time_provider,
)
from lovv_agent_v2.agents.planner.state.scratch import planner_scratch_mapping, planner_state_update
from lovv_agent_v2.agents.planner.steps.assemble_itinerary.node import assemble_itinerary_node
from lovv_agent_v2.agents.planner.steps.retrieve_places.festival_seed import festival_seed_places
from lovv_agent_v2.agents.planner.steps.retry_alternative_city.node import (
    fallback_to_alternative_city_node,
)


def retrieve_places(agent_input: Mapping[str, object]) -> dict[str, object]:
    request = _planner_agent_request(agent_input)
    place_pool = PlannerAgent(_planner_agent_tools(agent_input)).retrieve_places(request)
    return planner_state_update(agent_input, scratch_updates={"place_pool": place_pool})


def route_days_step(agent_input: Mapping[str, object]) -> dict[str, object]:
    request = _planner_agent_request(agent_input)
    pool = planner_scratch_mapping(agent_input, "place_pool", "planner.scratch.place_pool")
    selection, route = PlannerAgent(_planner_agent_tools(agent_input)).route_place_pool(request, pool)
    return planner_state_update(agent_input, scratch_updates={"selection": selection, "route": route})


def assemble_itinerary_step(agent_input: Mapping[str, object]) -> dict[str, object]:
    return assemble_itinerary_node(agent_input)


def retry_alternative_city(agent_input: Mapping[str, object]) -> dict[str, object]:
    return fallback_to_alternative_city_node(agent_input)


def _planner_agent_request(agent_input: Mapping[str, object]) -> PlannerAgentRequest:
    current_input = planner_input(agent_input)
    selected_city = mapping(current_input["selected_city"], "selected_city")
    raw_places, soft_places = fallback_places(agent_input)
    return PlannerAgentRequest(
        selected_city=selected_city,
        city_id=optional_text(current_input["city_id"]),
        ddb_pk=optional_text(current_input["ddb_pk"]),
        raw_query=current_input["raw_query"] if isinstance(current_input["raw_query"], str) else "",
        soft_query=current_input["soft_query"] if isinstance(current_input["soft_query"], str) else "",
        seeds=mapping_sequence(current_input["seeds"]),
        active_themes=string_tuple(current_input["active_themes"]),
        preferred_themes=string_tuple(current_input["preferred_themes"]),
        theme_weights=theme_weights(current_input["theme_weights"]),
        trip_type=text(current_input["trip_type"], "trip_type"),
        transport_pref=text(current_input["transport_pref"], "transport_pref"),
        min_count=int_value(current_input["min_count"], "min_count"),
        target_count=int_value(current_input["target_count"], "target_count"),
        raw_query_vector=current_input["raw_query_vector"]
        if isinstance(current_input["raw_query_vector"], tuple)
        else (),
        fallback_raw_places=raw_places,
        fallback_soft_places=soft_places,
        festival_places=festival_seed_places(agent_input, selected_city),
    )


def _planner_agent_tools(agent_input: Mapping[str, object]) -> PlannerAgentTools:
    return PlannerAgentTools(
        runtime=runtime_tools(agent_input),
        travel_time_provider=travel_time_provider(agent_input),
    )
