"""Response Packager Node."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.types import interrupt

from lovv_agent_v2.agents.response_packager.agent import ResponsePackagerAgent
from lovv_agent_v2.agents.response_packager.contracts import ResponsePackagerInput
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.schemas import SchemaValidationError


def response_packager_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Format and pack output response. Triggers checkpointer interrupt."""
    output = ResponsePackagerAgent().run(_response_packager_input(state))
    if output.response.get("response_status") == "END_WAIT_USER":
        resume_value = interrupt(output.response["response_payload"])
        next_response = dict(output.response)
        next_response["clarification_resume"] = resume_value
        return {"response": next_response}
    return {"response": output.response}


def _response_packager_input(state: Mapping[str, Any]) -> ResponsePackagerInput:
    return ResponsePackagerInput(
        request=_request_payload(state),
        planner_output=_planner_output(state),
        selected_city=_selected_city(state),
        festival_verifications=_festival_verifications(state),
        unsupported_conditions=_unsupported_conditions(state),
        clarification=_clarification_payload(state),
    )


def _request_payload(state: Mapping[str, Any]) -> Mapping[str, Any]:
    city_input = _intent_city_input(state)
    request = state.get("request")
    if isinstance(request, Mapping):
        return _request_with_city_input(request, city_input)
    if city_input is not None:
        return _request_from_city_input(city_input)
    raise SchemaValidationError("state.request or intent.city_select_input is required")


def _intent_city_input(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        city_input = intent.get("city_select_input")
        if isinstance(city_input, Mapping):
            return city_input
    return None


def _request_with_city_input(
    request: Mapping[str, Any],
    city_input: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(request)
    if city_input is None:
        return payload
    payload.setdefault("country", city_input.get("country"))
    payload.setdefault("travel_month", city_input.get("travel_month"))
    payload.setdefault("trip_type", city_input.get("trip_type"))
    payload.setdefault("destination_id", city_input.get("destination_id"))
    payload.setdefault("themes", city_input.get("active_required_themes", ()))
    return payload


def _request_from_city_input(city_input: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": "mock-v2-request",
        "country": city_input.get("country"),
        "travel_month": city_input.get("travel_month"),
        "trip_type": city_input.get("trip_type"),
        "destination_id": city_input.get("destination_id"),
        "themes": city_input.get("active_required_themes", ()),
    }


def _clarification_payload(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        modify_intent = intent.get("modify_intent")
        if isinstance(modify_intent, Mapping):
            clarification = modify_intent.get("clarification")
            if isinstance(clarification, Mapping):
                return _modify_clarification_payload(clarification)
        clarification = intent.get("clarification")
        if intent.get("intent_type") == "modification" and isinstance(
            clarification,
            Mapping,
        ):
            return _modify_clarification_payload(clarification)
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


def _modify_clarification_payload(clarification: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(clarification)
    options = payload.get("options")
    if isinstance(options, list) and options:
        return payload
    payload["options"] = [
        {
            "option_id": "revise_modify_query",
            "label": "수정 요청 다시 입력",
            "apply": {},
            "then": "abort",
        },
    ]
    return payload


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
    if not isinstance(verified, list):
        return ()
    verifications: list[dict[str, Any]] = []
    for city in verified:
        if not isinstance(city, Mapping):
            continue
        festivals = city.get("festivals")
        if not isinstance(festivals, list):
            continue
        for festival in festivals:
            if isinstance(festival, Mapping):
                verifications.append(_festival_verification_payload(festival))
    return tuple(verifications)


def _festival_verification_payload(festival: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "festival_id": festival.get("festival_id"),
        "name": festival.get("name"),
        "date_status": festival.get("date_status", "confirmed"),
        "start_date": festival.get("event_start_date", festival.get("start_date")),
        "end_date": festival.get("event_end_date", festival.get("end_date")),
        "is_applicable_to_trip": True,
        "planner_policy": "placeable",
        "source_type": festival.get("source", "dynamodb"),
        "confidence": festival.get("confidence", 1.0),
        "evidence_summary": "festival gate confirmed this festival for the requested month",
    }


def _unsupported_conditions(state: Mapping[str, Any]) -> tuple[str, ...]:
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return ()
    values: list[str] = []
    _extend_texts(values, intent.get("unsupported_conditions"))
    _extend_texts(values, intent.get("unsupported_reasons"))
    modify_intent = intent.get("modify_intent")
    if isinstance(modify_intent, Mapping):
        _extend_texts(values, modify_intent.get("unsupported_reasons"))
    return tuple(values)


def _extend_texts(target: list[str], value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        return
    target.extend(str(item) for item in value)
