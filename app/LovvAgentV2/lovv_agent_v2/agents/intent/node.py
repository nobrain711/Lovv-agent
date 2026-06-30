"""Intent Node definition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.city_identity import enrich_city_select_identity
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def intent_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Interpret query and determine if modification is requested."""
    intent = _intent_payload(state)
    city_input = _city_select_input(intent, state.get("request"))
    enriched_input = enrich_city_select_identity(city_input)
    normalized_input = CitySelectInput.from_mapping(enriched_input).to_dict()
    next_intent = dict(intent)
    next_intent["city_select_input"] = normalized_input
    next_intent.setdefault("cleaned_raw_query", normalized_input["cleaned_raw_query"])
    next_intent.setdefault(
        "soft_preference_query",
        normalized_input["soft_preference_query"],
    )
    next_intent.setdefault(
        "unsupported_conditions",
        normalized_input["unsupported_conditions"],
    )
    return {"intent": next_intent}


def _intent_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        return dict(intent)
    return {}


def _city_select_input(
    intent: Mapping[str, Any],
    request: Any,
) -> Mapping[str, Any]:
    value = intent.get("city_select_input")
    if value is None:
        value = intent.get("intent_output")
    if isinstance(value, Mapping):
        return value
    if isinstance(request, Mapping):
        return _city_select_input_from_request(request)
    raise SchemaValidationError("intent.city_select_input or state.request is required")


def _city_select_input_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    themes = request.get("themes", request.get("active_required_themes", ()))
    return {
        "country": _first_present(request, "country"),
        "travel_month": _first_present(request, "travel_month", "travelMonth"),
        "travel_year": _first_present(request, "travel_year", "travelYear"),
        "trip_type": _first_present(request, "trip_type", "tripType"),
        "active_required_themes": themes,
        "include_festivals": _first_present(
            request,
            "include_festivals",
            "includeFestivals",
        ),
        "cleaned_raw_query": request.get("raw_query", request.get("rawQuery", "")),
        "soft_preference_query": request.get(
            "soft_preference_query",
            request.get("softPreferenceQuery", ""),
        ),
        "unsupported_conditions": request.get("unsupported_conditions", ()),
        "destination_id": request.get("destination_id", request.get("destinationId")),
        "city_key": request.get("city_key", request.get("cityKey")),
        "ddb_pk": request.get("ddb_pk", request.get("ddbPk")),
        "user_location": request.get("user_location", request.get("userLocation")),
        "execution_mode": request.get("execution_mode", "city_discovery"),
        "congestion_pref": request.get("congestion_pref", "neutral"),
        "transport_pref": request.get("transport_pref", "unknown"),
    }


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise SchemaValidationError(f"missing required request field: {keys[0]}")
