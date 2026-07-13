from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.models.city_identity import enrich_city_select_identity
from lovv_agent_v2.models.profile import LovvUserProfile, build_profile_theme_weights
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError
from lovv_agent_v2.models.trip_intent import trip_intent_from_mapping

CONFIRMATION_INTENT_VALUES = frozenset(
    {
        "itinerary_confirmed",
        "itinerary_confirmation",
        "confirm_itinerary",
        "confirm",
        "confirmed",
        "일정_확정",
    },
)
CONFIRMATION_FIELD_NAMES = (
    "intent_type",
    "intentType",
    "action",
    "entry_type",
    "entryType",
)


def mock_intent_node(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    intent = _intent_payload(state)
    if _is_itinerary_confirmation(intent):
        next_intent = dict(intent)
        next_intent["intent_mode"] = "mock_passthrough"
        return {"intent": next_intent}

    city_input = enrich_city_select_identity(_city_select_source(state, intent))
    normalized_input = CitySelectInput.from_mapping(city_input).to_dict()
    next_intent = dict(intent)
    next_intent["city_select_input"] = normalized_input
    next_intent["intent_mode"] = "mock_generation"
    trip_intent = trip_intent_from_mapping(normalized_input)
    if trip_intent is not None:
        next_intent["trip_intent"] = trip_intent
    return {"intent": next_intent}


def mock_profile_node(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    intent = _intent_payload(state)
    if _is_itinerary_confirmation(intent):
        return _profile_confirmation_update(state, intent)

    normalized_input = CitySelectInput.from_mapping(_city_select_source(state, intent)).to_dict()
    profile = _profile_from_state(state)
    weights = build_profile_theme_weights(
        profile,
        normalized_input["active_required_themes"],
    )
    if weights.active and weights.theme_weights:
        normalized_input["theme_weights"] = weights.theme_weights
    elif "theme_weights" in normalized_input:
        normalized_input.pop("theme_weights")

    next_intent = dict(intent)
    next_intent["city_select_input"] = normalized_input
    trip_intent = trip_intent_from_mapping(normalized_input)
    if trip_intent is not None:
        next_intent["trip_intent"] = trip_intent

    next_profile = _profile_payload(state)
    audit = weights.to_audit()
    next_profile["saved_trip_count"] = profile.saved_trip_count if profile is not None else 0
    next_profile["profile_theme_weights"] = audit["theme_id_weights"]
    next_profile["effective_theme_weights"] = (
        dict(weights.theme_weights) if weights.active and weights.theme_weights else None
    )
    next_profile["applied_persona_id"] = _applied_persona_id(next_profile)
    next_profile["audit"] = audit
    return {"intent": next_intent, "profile": next_profile}


def _intent_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        raise SchemaValidationError("state.intent is required before mock contract nodes")
    return dict(intent)


def _city_select_source(
    state: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> Mapping[str, Any]:
    for value in (
        intent.get("city_select_input"),
        state.get("request"),
    ):
        if isinstance(value, Mapping):
            return value
    raise SchemaValidationError("mock contract requires city_select_input or request")


def _profile_confirmation_update(
    state: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    profile = _profile_from_state(state)
    next_profile = _profile_payload(state)
    saved_trip_count = profile.saved_trip_count if profile is not None else 0
    next_profile["saved_trip_count"] = saved_trip_count + 1
    next_profile["profile_update"] = _confirmation_update_payload(intent)
    next_profile["audit"] = {
        "profile_update_requested": True,
        "profile_update_reason": "itinerary_confirmed",
    }
    return {"intent": dict(intent), "profile": next_profile}


def _confirmation_update_payload(intent: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "recorded",
        "reason": "itinerary_confirmed",
    }
    for output_key, input_keys in (
        ("recommendation_id", ("recommendation_id", "recommendationId")),
        ("itinerary_id", ("itinerary_id", "itineraryId")),
    ):
        value = _first_text(intent, input_keys)
        if value is not None:
            payload[output_key] = value
    return payload


def _profile_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    profile = state.get("profile", {})
    return dict(profile) if isinstance(profile, Mapping) else {}


def _profile_from_state(state: Mapping[str, Any]) -> LovvUserProfile | None:
    profile = _profile_payload(state)
    value = profile.get("lovv_user_profile")
    if value is None:
        value = profile.get("mock_profile")
    if value is None:
        profile_record = profile.get("profile_record")
        if isinstance(profile_record, Mapping):
            value = profile_record.get("lovv_user_profile")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SchemaValidationError("profile.lovv_user_profile must be an object")
    return LovvUserProfile.from_mapping(value)


def _applied_persona_id(profile: Mapping[str, Any]) -> str | None:
    profile_record = profile.get("profile_record")
    if not isinstance(profile_record, Mapping):
        return None
    value = profile_record.get("profile_id") or profile_record.get("actor_id")
    return value if isinstance(value, str) and value.strip() else None


def _is_itinerary_confirmation(intent: Mapping[str, Any]) -> bool:
    return any(
        _normalized_intent_value(intent.get(field_name)) in CONFIRMATION_INTENT_VALUES
        for field_name in CONFIRMATION_FIELD_NAMES
    )


def _normalized_intent_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _first_text(mapping: Mapping[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        value = mapping.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
