from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def weather_planner_output(state: Mapping[str, Any]) -> Mapping[str, Any]:
    planner = _mapping(state.get("planner"))
    return _mapping(planner.get("planner_output"))


def weather_request_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    request = dict(_mapping(state.get("request")))
    city_input = _mapping(_mapping(state.get("intent")).get("city_select_input"))
    return {
        "request_id": _first_text(request, "request_id", "requestId", "thread_id", "threadId")
        or "weather-alternative",
        "country": _first_text(request, "country") or _first_text(city_input, "country") or "KR",
        "travel_month": _first_value(request, "travel_month", "travelMonth")
        or _first_value(city_input, "travel_month", "travelMonth"),
        "trip_type": _first_text(request, "trip_type", "tripType")
        or _first_text(city_input, "trip_type", "tripType")
        or "2d1n",
        "destination_id": _first_value(city_input, "destination_id", "destinationId")
        or _first_value(request, "destination_id", "destinationId"),
        "themes": tuple(request.get("themes", city_input.get("active_required_themes", ()))),
    }


def weather_selected_city(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    selected = planner_output.get("selected_city")
    if isinstance(selected, Mapping):
        return selected
    city_select = _mapping(state.get("city_select"))
    result = _mapping(city_select.get("city_selection_result"))
    selected = result.get("selected_city")
    return selected if isinstance(selected, Mapping) else None


def weather_recommendation_id(response: Mapping[str, Any]) -> str | None:
    payload = response.get("response_payload")
    if not isinstance(payload, Mapping):
        return None
    return _text(payload.get("recommendationId", payload.get("recommendation_id")))


def _first_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    return next((mapping[key] for key in keys if key in mapping), None)


def _first_text(mapping: Mapping[str, Any], *keys: str) -> str | None:
    return _text(_first_value(mapping, *keys))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "weather_planner_output",
    "weather_recommendation_id",
    "weather_request_payload",
    "weather_selected_city",
]
