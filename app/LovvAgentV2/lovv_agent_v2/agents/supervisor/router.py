from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.supervisor.confirmation_routing import (
    is_itinerary_confirmation_state,
)
from lovv_agent_v2.agents.supervisor.modify_routing import (
    has_current_modify_response_payload,
    modify_intent_from_state,
    modify_intent_needs_response,
    modify_intent_routes_slot_replace_planner,
    slot_replace_applied,
    slot_replace_failed,
)
from lovv_agent_v2.core.state import UnifiedAgentState

END_ROUTE = "end"


def supervisor_node(state: UnifiedAgentState) -> dict[str, dict[str, Any]]:
    reason_code = _clarification_reason_code(state)
    next_node = _next_node(state, reason_code=reason_code)
    completed_groups = _completed_groups(state)
    return {
        "routing": {
            "next_node": next_node,
            "completed_groups": completed_groups,
            "needs_clarification": reason_code is not None,
            "clarification_reason_code": reason_code,
        },
    }


def route_next_action(state: UnifiedAgentState) -> str:
    routing = supervisor_node(state)["routing"]
    next_node = routing.get("next_node")
    return next_node if isinstance(next_node, str) else END_ROUTE


def _next_node(state: Mapping[str, Any], *, reason_code: str | None) -> str:
    modify_intent = modify_intent_from_state(state)
    if is_itinerary_confirmation_state(state):
        return END_ROUTE if _has_profile_update(state) else "profile"
    if _has_current_modify_response_payload(state, modify_intent):
        return END_ROUTE
    if slot_replace_failed(state):
        return "response_packager"
    if modify_intent_routes_slot_replace_planner(state, modify_intent):
        return "planner"
    if _modify_intent_routes_direct_anchor_planner(state, modify_intent):
        return "planner"
    if modify_intent_needs_response(modify_intent):
        return "response_packager"
    if _modify_intent_has_planner_output(state, modify_intent):
        if _has_current_modify_response_payload(state, modify_intent):
            return END_ROUTE
        if not _has_itinerary_explanation(state):
            return "explain_itinerary"
        return "response_packager" if _has_post_explain_weather(state) else "weather_alternative"
    if _has_response_payload(state):
        return END_ROUTE
    if reason_code is not None:
        return "response_packager"
    if not _has_profile_result(state):
        return "profile"
    if not _has_festival_gate_result(state) and not _festivals_excluded(state):
        return "festival_verifier"
    if _city_select_needs_response(state):
        return "response_packager"
    if not _has_planner_output(state):
        if _can_skip_city_select_for_direct_anchor(state):
            return "planner"
        if not _has_city_selection_result(state):
            return "city_select"
        return "planner"
    if not _has_itinerary_explanation(state):
        return "explain_itinerary"
    if not _has_post_explain_weather(state):
        return "weather_alternative"
    return "response_packager"


def _completed_groups(state: Mapping[str, Any]) -> list[str]:
    completed: list[str] = []
    if _has_profile_result(state):
        completed.append("profile")
    if _has_festival_gate_result(state) or _festivals_excluded(state):
        completed.append("festival_gate")
    if _has_city_select_result_or_terminal_status(state):
        completed.append("city_select")
    if _has_planner_output(state):
        completed.append("planner")
    if _has_response_payload(state):
        completed.append("response")
    return completed


def _clarification_reason_code(state: Mapping[str, Any]) -> str | None:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        value = _clarification_reason_from_group(intent)
        if value is not None:
            return value
    modify_intent = modify_intent_from_state(state)
    if modify_intent is not None:
        value = _clarification_reason_from_group(modify_intent)
        if value is not None:
            return value
    for group_name in ("festival_gate", "city_select", "response"):
        group = state.get(group_name)
        if isinstance(group, Mapping):
            value = _clarification_reason_from_group(group)
            if value is not None:
                return value
    return None


def _clarification_reason_from_group(group: Mapping[str, Any]) -> str | None:
    clarification = group.get("clarification")
    if not isinstance(clarification, Mapping):
        return None
    value = clarification.get("reason_code")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _modify_intent_routes_direct_anchor_planner(
    state: Mapping[str, Any],
    modify_intent: Mapping[str, Any] | None,
) -> bool:
    if modify_intent is None:
        return False
    return (
        not _has_planner_output(state)
        and not _has_city_select_result_or_terminal_status(state)
        and _can_skip_city_select_for_direct_anchor(state)
        and modify_intent.get("status") == "ok"
        and modify_intent.get("routing_hint") == "planner_direct_anchor"
    )


def _modify_intent_has_planner_output(
    state: Mapping[str, Any],
    modify_intent: Mapping[str, Any] | None,
) -> bool:
    if modify_intent is None:
        return False
    return modify_intent.get("status") == "ok" and _has_planner_output(state)


def _has_current_modify_response_payload(
    state: Mapping[str, Any],
    modify_intent: Mapping[str, Any] | None,
) -> bool:
    return modify_intent is not None and has_current_modify_response_payload(state, modify_intent)


def _has_profile_result(state: Mapping[str, Any]) -> bool:
    profile = state.get("profile")
    return isinstance(profile, Mapping) and "audit" in profile


def _has_profile_update(state: Mapping[str, Any]) -> bool:
    profile = state.get("profile")
    return isinstance(profile, Mapping) and isinstance(profile.get("profile_update"), Mapping)


def _has_festival_gate_result(state: Mapping[str, Any]) -> bool:
    festival_gate = state.get("festival_gate")
    return isinstance(festival_gate, Mapping) and (
        "result" in festival_gate or "audit" in festival_gate
    )


def _festivals_excluded(state: Mapping[str, Any]) -> bool:
    request = state.get("request")
    if isinstance(request, Mapping) and request.get("include_festivals") is False:
        return True
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return False
    city_input = intent.get("city_select_input")
    return isinstance(city_input, Mapping) and city_input.get("include_festivals") is False


def _can_skip_city_select_for_direct_anchor(state: Mapping[str, Any]) -> bool:
    if _has_city_select_result_or_terminal_status(state):
        return False
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return False
    city_input = intent.get("city_select_input")
    if not isinstance(city_input, Mapping):
        return False
    destination_id = city_input.get("destination_id")
    if not isinstance(destination_id, str) or not destination_id.strip():
        return False
    return _festivals_excluded(state) or _festival_gate_confirms_anchor(
        state,
        destination_id.strip(),
    )


def _has_city_selection_result(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    return isinstance(city_select.get("city_selection_result"), Mapping)


def _has_city_select_result_or_terminal_status(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    return isinstance(city_select.get("city_selection_result"), Mapping) or isinstance(
        city_select.get("status"),
        str,
    )


def _city_select_needs_response(state: Mapping[str, Any]) -> bool:
    city_select = state.get("city_select")
    if not isinstance(city_select, Mapping):
        return False
    if isinstance(city_select.get("city_selection_result"), Mapping):
        return False
    status = city_select.get("status")
    return isinstance(status, str) and status != "ok"


def _festival_gate_confirms_anchor(
    state: Mapping[str, Any],
    destination_id: str,
) -> bool:
    festival_gate = state.get("festival_gate")
    if not isinstance(festival_gate, Mapping):
        return False
    result = festival_gate.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "ok":
        return False
    allowed_city_ids = result.get("allowed_city_ids")
    if not isinstance(allowed_city_ids, (list, tuple)):
        return False
    normalized_destination = destination_id.strip()
    return any(city_id == normalized_destination for city_id in allowed_city_ids)


def _has_planner_output(state: Mapping[str, Any]) -> bool:
    planner = state.get("planner")
    return isinstance(planner, Mapping) and isinstance(planner.get("planner_output"), Mapping)


def _has_itinerary_explanation(state: Mapping[str, Any]) -> bool:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return False
    validation = planner.get("validation_result")
    if not isinstance(validation, Mapping):
        planner_output = planner.get("planner_output")
        if isinstance(planner_output, Mapping):
            validation = planner_output.get("validation_result")
    if not isinstance(validation, Mapping):
        return False
    return (
        "planner_copy_generation_used_llm" in validation
        or "detail_enrichment_warning_count" in validation
        or "itinerary_explanation_item_count" in validation
    )


def _has_post_explain_weather(state: Mapping[str, Any]) -> bool:
    validation = _planner_validation(state)
    weather_audit = validation.get("weather_audit")
    return isinstance(weather_audit, Mapping) and weather_audit.get("evaluation_stage") == "post_explain"


def _planner_validation(state: Mapping[str, Any]) -> Mapping[str, Any]:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return {}
    validation = planner.get("validation_result")
    if isinstance(validation, Mapping):
        return validation
    planner_output = planner.get("planner_output")
    if isinstance(planner_output, Mapping):
        output_validation = planner_output.get("validation_result")
        if isinstance(output_validation, Mapping):
            return output_validation
    return {}


def _has_response_payload(state: Mapping[str, Any]) -> bool:
    response = state.get("response")
    return isinstance(response, Mapping) and isinstance(response.get("response_payload"), Mapping)


__all__ = ["END_ROUTE", "route_next_action", "supervisor_node"]
