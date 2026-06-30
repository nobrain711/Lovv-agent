from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.profile import LovvUserProfile, build_profile_theme_weights
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError

def profile_node(state: UnifiedAgentState) -> dict:
    intent = _intent_payload(state)
    city_input = _city_select_input(intent)
    normalized_input = CitySelectInput.from_mapping(city_input).to_dict()
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
        raise SchemaValidationError("state.intent is required before profile_node")
    return dict(intent)


def _city_select_input(intent: Mapping[str, Any]) -> Mapping[str, Any]:
    city_input = intent.get("city_select_input")
    if city_input is None:
        city_input = intent.get("intent_output")
    if not isinstance(city_input, Mapping):
        raise SchemaValidationError("intent.city_select_input is required")
    return city_input


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
