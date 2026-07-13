from __future__ import annotations

from collections.abc import Sequence

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace
from lovv_agent_v2.agents.planner.steps.route_days.place_selection import PlannerSelectionResult
from lovv_agent_v2.agents.planner.steps.route_days.routing import RouteDay, RoutedPlace, RoutingResult


def selection_payload(
    selection: PlannerSelectionResult,
    reserve: Sequence[PlannerPlace],
    *,
    min_count: int,
    target_count: int,
    routable_count: int,
) -> dict[str, object]:
    return {
        "places": tuple(planner_place_payload(place) for place in selection.places),
        "reserve": tuple(planner_place_payload(place) for place in reserve),
        "audit": {
            **selection.audit,
            "min_count": min_count,
            "target_count": target_count,
            "selected_count": len(selection.places),
            "routable_count": routable_count,
        },
    }


def route_payload(route_result: RoutingResult, reserve: Sequence[PlannerPlace]) -> dict[str, object]:
    return {
        "days": tuple(_day_payload(day) for day in route_result.days),
        "reserve": tuple(planner_place_payload(place) for place in reserve),
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
        "place": planner_place_payload(routed_place.place),
        "move_min_from_prev": routed_place.move_min_from_prev,
    }


def planner_place_payload(place: PlannerPlace) -> dict[str, object]:
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
