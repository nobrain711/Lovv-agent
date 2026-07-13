from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def trip_intent_from_intent(intent: Mapping[str, Any]) -> dict[str, Any] | None:
    for key in ("trip_intent", "city_select_input"):
        payload = intent.get(key)
        if isinstance(payload, Mapping):
            trip_intent = trip_intent_from_mapping(payload)
            if trip_intent is not None:
                return trip_intent
    return None


def trip_intent_from_mapping(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    country = _text(_first_present(payload, "country"))
    travel_month = _first_present(payload, "travel_month", "travelMonth")
    trip_type = _text(_first_present(payload, "trip_type", "tripType"))
    themes = _themes(_first_present(payload, "themes", "active_required_themes"))
    include_festivals = _first_present(payload, "include_festivals", "includeFestivals")
    raw_query = _text(_first_present(payload, "raw_query", "cleaned_raw_query"))
    if (
        country is None
        or not isinstance(travel_month, int)
        or trip_type is None
        or not themes
        or not isinstance(include_festivals, bool)
        or raw_query is None
    ):
        return None
    trip_intent: dict[str, Any] = {
        "country": country,
        "travel_month": travel_month,
        "travel_year": _first_present(payload, "travel_year", "travelYear"),
        "trip_type": trip_type,
        "themes": themes,
        "include_festivals": include_festivals,
        "raw_query": raw_query,
        "soft_preference_query": _text(
            _first_present(payload, "soft_preference_query", "soft_query"),
        )
        or "",
        "destination_id": _first_present(payload, "destination_id", "destinationId"),
        "user_location": _first_present(payload, "user_location", "userLocation"),
        "execution_mode": _first_present(payload, "execution_mode", "executionMode"),
        "congestion_pref": _text(
            _first_present(payload, "congestion_pref", "congestionPref"),
        )
        or "neutral",
        "transport_pref": _text(
            _first_present(payload, "transport_pref", "transportPref"),
        )
        or "unknown",
        "unsupported_conditions": tuple(
            _sequence(_first_present(payload, "unsupported_conditions", "unsupportedConditions")),
        ),
    }
    _copy_optional(
        trip_intent,
        payload,
        (
            "theme_weights",
            "city_key",
            "ddb_pk",
            "destination_label",
            "province",
            "preferred_theme_ids",
            "disliked_theme_ids",
            "preferred_region_ids",
            "disliked_region_ids",
            "preferred_region_spans",
            "disliked_region_spans",
            "unresolved_region_spans",
            "preferred_region_names",
            "disliked_region_names",
            "needs_clarification",
            "clarifying_question",
            "contradiction_reasons",
        ),
    )
    return trip_intent


def city_select_input_from_trip_intent(trip_intent: Mapping[str, Any]) -> dict[str, Any]:
    city_input = {
        "country": trip_intent.get("country"),
        "travel_month": trip_intent.get("travel_month"),
        "travel_year": trip_intent.get("travel_year"),
        "trip_type": trip_intent.get("trip_type"),
        "active_required_themes": tuple(_sequence(trip_intent.get("themes"))),
        "include_festivals": trip_intent.get("include_festivals"),
        "cleaned_raw_query": trip_intent.get("raw_query"),
        "soft_preference_query": trip_intent.get("soft_preference_query", ""),
        "unsupported_conditions": tuple(_sequence(trip_intent.get("unsupported_conditions"))),
        "destination_id": trip_intent.get("destination_id"),
        "user_location": trip_intent.get("user_location"),
        "execution_mode": trip_intent.get("execution_mode"),
        "congestion_pref": trip_intent.get("congestion_pref", "neutral"),
        "transport_pref": trip_intent.get("transport_pref", "unknown"),
    }
    _copy_optional(
        city_input,
        trip_intent,
        (
            "theme_weights",
            "city_key",
            "ddb_pk",
            "destination_label",
            "province",
            "preferred_theme_ids",
            "disliked_theme_ids",
            "preferred_region_ids",
            "disliked_region_ids",
            "preferred_region_spans",
            "disliked_region_spans",
            "unresolved_region_spans",
            "preferred_region_names",
            "disliked_region_names",
            "needs_clarification",
            "clarifying_question",
            "contradiction_reasons",
        ),
    )
    return city_input


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _copy_optional(
    target: dict[str, Any],
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if key in source and source[key] is not None:
            target[key] = source[key]


def _themes(value: Any) -> tuple[str, ...]:
    return tuple(_sequence(value))


def _sequence(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "city_select_input_from_trip_intent",
    "trip_intent_from_intent",
    "trip_intent_from_mapping",
]
