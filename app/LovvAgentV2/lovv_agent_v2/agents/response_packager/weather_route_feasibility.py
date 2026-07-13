from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.planner.domain.place_model import coerce_place
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import (
    DurationLookup,
    max_leg_min,
)
from lovv_agent_v2.agents.planner.steps.route_days.trim_policy import MAX_HARD_LEG_MIN
from lovv_agent_v2.tools.travel_time import travel_time_provider_from_value
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.models.schemas import SchemaValidationError


def weather_route_feasible(
    state: Mapping[str, Any],
    original: Sequence[Mapping[str, Any]],
    alternative: Sequence[Mapping[str, Any]],
) -> bool:
    provider = travel_time_provider_from_value(runtime_value(state, "travel_time_provider"))
    transport_pref = _transport_pref(state)
    for day in _changed_days(original, alternative):
        day_items = _day_items(alternative, day)
        snapped = provider.snap_places(day_items, transport_pref)
        if snapped.excluded_place_ids or len(snapped.places) != len(day_items):
            return False
        place_ids = _place_ids(snapped.places)
        if place_ids is None:
            return False
        matrix = provider.matrix_minutes(place_ids, transport_pref)
        if not _within_hard_leg(snapped.places, matrix.durations):
            return False
    return True


def _changed_days(
    original: Sequence[Mapping[str, Any]],
    alternative: Sequence[Mapping[str, Any]],
) -> tuple[int, ...]:
    days: list[int] = []
    for original_item, alternative_item in zip(original, alternative, strict=False):
        if _place_id(original_item) != _place_id(alternative_item):
            days.append(_day(alternative_item))
    return tuple(dict.fromkeys(days))


def _day_items(items: Sequence[Mapping[str, Any]], day: int) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in items if _day(item) == day)


def _within_hard_leg(
    items: Sequence[Mapping[str, Any]],
    durations: Mapping[tuple[str, str], float],
) -> bool:
    try:
        places = tuple(coerce_place(item) for item in items)
    except SchemaValidationError:
        return False
    return max_leg_min(places, DurationLookup(durations)) <= MAX_HARD_LEG_MIN


def _transport_pref(state: Mapping[str, Any]) -> str:
    request = _mapping(state.get("request"))
    city_input = _mapping(_mapping(state.get("intent")).get("city_select_input"))
    value = request.get("transportPref", request.get("transport_pref"))
    if not isinstance(value, str) or not value.strip():
        value = city_input.get("transport_pref", city_input.get("transportPref"))
    return value.strip() if isinstance(value, str) and value.strip() else "car"


def _place_ids(items: Sequence[Mapping[str, Any]]) -> tuple[str, ...] | None:
    values = tuple(_place_id(item) for item in items)
    if any(value is None for value in values):
        return None
    return tuple(value for value in values if value is not None)


def _place_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("place_id", item.get("placeId", item.get("contentId")))
    return value.strip() if isinstance(value, str) and value.strip() else None


def _day(item: Mapping[str, Any]) -> int:
    value = item.get("day")
    return value if isinstance(value, int) and not isinstance(value, bool) else 1


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["weather_route_feasible"]
