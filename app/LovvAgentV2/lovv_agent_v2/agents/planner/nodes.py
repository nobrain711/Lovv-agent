from __future__ import annotations

from collections.abc import Mapping, Sequence

from lovv_agent_v2.agents.planner.assemble import assemble_itinerary_node
from lovv_agent_v2.agents.planner.context import (
    PlannerRuntimeTools,
    candidate_payloads,
    fallback_places,
    int_value,
    mapping,
    mapping_sequence,
    optional_text,
    place_id,
    planner_input,
    runtime_tools,
    string_tuple,
    text,
    theme_weights,
    top_k,
    travel_time_provider,
)
from lovv_agent_v2.agents.planner.place_selection import (
    PlannerPlace,
    PlannerSelectionInput,
    PlannerSelectionResult,
    build_working_set,
)
from lovv_agent_v2.agents.planner.routing import RouteDay, RoutedPlace, RoutingResult, route_days


def retrieve_places_node(state: Mapping[str, object]) -> dict[str, object]:
    current_input = planner_input(state)
    runtime = runtime_tools(state)
    if runtime is None:
        raw_places, soft_places = fallback_places(state)
        return {
            "planner_place_pool": {
                "raw_places": raw_places,
                "soft_places": soft_places,
                "audit": _retrieve_audit(current_input, "city_select_scoring_audit_fallback", raw_places, soft_places),
            },
        }
    raw_places = candidate_payloads(
        runtime.destination_search.search_candidates(
            runtime.embedding.embed_query(text(current_input["raw_query"], "cleaned_raw_query")),
            top_k=top_k(current_input["target_count"]),
            city_id=optional_text(current_input["city_id"]),
            ddb_pk=optional_text(current_input["ddb_pk"]),
            theme=None,
        ),
        similarity_key="raw_similarity",
    )
    soft_places = _soft_channel(current_input, runtime)
    return {
        "planner_place_pool": {
            "raw_places": raw_places,
            "soft_places": soft_places,
            "audit": _retrieve_audit(current_input, "planner_city_anchored_vector_search", raw_places, soft_places),
        },
    }


def route_days_node(state: Mapping[str, object]) -> dict[str, object]:
    current_input = planner_input(state)
    pool = mapping(state.get("planner_place_pool"), "planner_place_pool")
    selection = build_working_set(
        PlannerSelectionInput(
            raw_places=mapping_sequence(pool.get("raw_places")),
            soft_places=mapping_sequence(pool.get("soft_places")),
            seeds=mapping_sequence(current_input["seeds"]),
            active_themes=string_tuple(current_input["active_themes"]),
            theme_weights=theme_weights(current_input["theme_weights"]),
            trip_type=text(current_input["trip_type"], "trip_type"),
            target_count=int_value(current_input["target_count"], "target_count"),
        ),
    )
    provider = travel_time_provider(state)
    transport_pref = text(current_input["transport_pref"], "transport_pref")
    snapped = provider.snap_places(tuple(place.payload for place in selection.places), transport_pref)
    excluded_ids = set(snapped.excluded_place_ids)
    snapped_ids = {place_id(place) for place in snapped.places}
    routable = tuple(place for place in selection.places if place.place_id in snapped_ids and place.place_id not in excluded_ids)
    unroutable = tuple(place for place in selection.places if place.place_id not in {item.place_id for item in routable})
    matrix = provider.matrix_minutes(tuple(place.place_id for place in routable), transport_pref)
    routed = route_days(
        routable,
        trip_type=text(current_input["trip_type"], "trip_type"),
        transport_pref=transport_pref,
        durations=matrix.durations,
        provider_audit={
            **dict(snapped.audit),
            **dict(matrix.audit),
            "unroutable_place_ids": tuple(place.place_id for place in unroutable),
        },
    )
    reserve = (*selection.reserve, *unroutable, *routed.reserve)
    return {
        "planner_selection": _selection_payload(selection, reserve, current_input, len(routable)),
        "planner_route": _route_payload(routed, reserve),
    }


def _soft_channel(
    current_input: Mapping[str, object],
    runtime: PlannerRuntimeTools,
) -> tuple[Mapping[str, object], ...]:
    soft_query = optional_text(current_input["soft_query"])
    if not soft_query:
        return ()
    return candidate_payloads(
        runtime.destination_search.search_candidates(
            runtime.embedding.embed_query(soft_query),
            top_k=top_k(current_input["target_count"]),
            city_id=optional_text(current_input["city_id"]),
            ddb_pk=optional_text(current_input["ddb_pk"]),
            theme=None,
        ),
        similarity_key="soft_similarity",
    )


def _retrieve_audit(
    current_input: Mapping[str, object],
    source: str,
    raw_places: Sequence[Mapping[str, object]],
    soft_places: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "retrieve_source": source,
        "city_id": current_input["city_id"],
        "ddb_pk": current_input["ddb_pk"],
        "raw_channel_theme": None,
        "soft_channel_theme": None,
        "raw_count": len(raw_places),
        "soft_count": len(soft_places),
    }


def _selection_payload(
    selection: PlannerSelectionResult,
    reserve: Sequence[PlannerPlace],
    current_input: Mapping[str, object],
    routable_count: int,
) -> dict[str, object]:
    return {
        "places": tuple(_planner_place_payload(place) for place in selection.places),
        "reserve": tuple(_planner_place_payload(place) for place in reserve),
        "audit": {
            **selection.audit,
            "target_count": current_input["target_count"],
            "selected_count": len(selection.places),
            "routable_count": routable_count,
        },
    }


def _route_payload(route_result: RoutingResult, reserve: Sequence[PlannerPlace]) -> dict[str, object]:
    return {
        "days": tuple(_day_payload(day) for day in route_result.days),
        "reserve": tuple(_planner_place_payload(place) for place in reserve),
        "audit": route_result.audit,
    }


def _day_payload(day: RouteDay) -> dict[str, object]:
    return {
        "day": day.day,
        "anchor_place_id": day.anchor_place_id,
        "anchor_type": day.anchor_type,
        "places": tuple(_routed_place_payload(place) for place in day.places),
        "day_travel_min": day.day_travel_min,
    }


def _routed_place_payload(routed_place: RoutedPlace) -> dict[str, object]:
    return {
        "place": _planner_place_payload(routed_place.place),
        "move_min_from_prev": routed_place.move_min_from_prev,
    }


def _planner_place_payload(place: PlannerPlace) -> dict[str, object]:
    payload = dict(place.payload)
    payload.update(
        {
            "place_id": place.place_id,
            "title": place.title,
            "theme_tags": place.theme_tags,
            "assigned_theme": place.assigned_theme,
            "similarity": place.similarity,
            "soft_similarity": place.soft_similarity,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "is_seed": place.is_seed,
        },
    )
    return payload
