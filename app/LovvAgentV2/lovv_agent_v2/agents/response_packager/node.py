"""Response Packager Node."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.agents.response_packager.packager import package_recommendation_response
from lovv_agent_v2.models.schemas import SchemaValidationError


def response_packager_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Format and pack output response. Triggers checkpointer interrupt."""
    request = _request_payload(state)
    clarification = _clarification_payload(state)
    response_status = "END_WAIT_USER" if clarification is not None else "completed"
    payload = package_recommendation_response(
        planner_output=_planner_output(state),
        request=request,
        selected_city=_selected_city(state),
        festival_verifications=_festival_verifications(state),
        unsupported_conditions=_unsupported_conditions(state),
        recommendation_id=_recommendation_id(request),
        response_status=response_status,
        clarification=clarification,
    )
    return {
        "response": {
            "response_status": response_status,
            "response_payload": payload,
            "clarification": clarification,
        },
    }


def _request_payload(state: Mapping[str, Any]) -> Mapping[str, Any]:
    request = state.get("request")
    if isinstance(request, Mapping):
        return request
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        city_input = intent.get("city_select_input")
        if isinstance(city_input, Mapping):
            return {
                "request_id": "mock-v2-request",
                "country": city_input.get("country"),
                "travel_month": city_input.get("travel_month"),
                "trip_type": city_input.get("trip_type"),
                "destination_id": city_input.get("destination_id"),
                "themes": city_input.get("active_required_themes", ()),
            }
    raise SchemaValidationError("state.request or intent.city_select_input is required")


def _clarification_payload(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    festival_gate = state.get("festival_gate")
    if isinstance(festival_gate, Mapping):
        clarification = festival_gate.get("clarification")
        if isinstance(clarification, Mapping):
            return clarification
    response = state.get("response")
    if isinstance(response, Mapping):
        clarification = response.get("clarification")
        if isinstance(clarification, Mapping):
            return clarification
    return None


def _planner_output(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    planner = state.get("planner")
    if isinstance(planner, Mapping):
        planner_output = planner.get("planner_output")
        if isinstance(planner_output, Mapping):
            return planner_output
    return None


def _selected_city(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    city_select = state.get("city_select")
    if isinstance(city_select, Mapping):
        city_selection_result = city_select.get("city_selection_result")
        if isinstance(city_selection_result, Mapping):
            selected_city = city_selection_result.get("selected_city")
            if isinstance(selected_city, Mapping):
                return selected_city
    return None


def _festival_verifications(state: Mapping[str, Any]) -> tuple[Any, ...]:
    festival_gate = state.get("festival_gate")
    if not isinstance(festival_gate, Mapping):
        return ()
    result = festival_gate.get("result")
    if not isinstance(result, Mapping):
        return ()
    verified = result.get("verified_festival_cities")
    return tuple(verified) if isinstance(verified, list) else ()


def _unsupported_conditions(state: Mapping[str, Any]) -> tuple[str, ...]:
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return ()
    value = intent.get("unsupported_conditions")
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _recommendation_id(request: Mapping[str, Any]) -> str | None:
    value = request.get("request_id", request.get("requestId"))
    return value if isinstance(value, str) else None
