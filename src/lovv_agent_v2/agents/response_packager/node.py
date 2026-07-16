"""Response Packager Node."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.types import interrupt

from lovv_agent_v2.agents.response_packager.agent import ResponsePackagerAgent
from lovv_agent_v2.agents.response_packager.clarification_resume import response_resume_update
from lovv_agent_v2.agents.response_packager.contracts import ResponsePackagerInput
from lovv_agent_v2.common.telemetry_lifecycle import emit_clarification_waiting
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.clarification_texts import (
    clarification_helper_text,
    clarification_label_text,
    clarification_prompt_text,
)
from lovv_agent_v2.models.schemas import SchemaValidationError

RELAXED_GENERATION_THEMES: tuple[str, ...] = (
    "바다·해안",
    "자연·트레킹",
    "역사·전통",
    "예술·감성",
    "온천·휴양",
)


def response_packager_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Format and pack output response. Triggers checkpointer interrupt."""
    output = ResponsePackagerAgent().run(_response_packager_input(state))
    if output.response.get("response_status") == "END_WAIT_USER":
        emit_clarification_waiting(state, output.response)
        if runtime_value(state, "interrupts_enabled") is False:
            return {"response": output.response}
        resume_value = interrupt(output.response["response_payload"])
        return response_resume_update(state, output.response, resume_value)
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
        return _request_with_city_input(
            request,
            city_input,
            prefer_city_input_destination=_is_city_change(state),
        )
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
    *,
    prefer_city_input_destination: bool,
) -> dict[str, Any]:
    payload = dict(request)
    destination_id = request.get("destinationId")
    if destination_id is not None:
        payload.setdefault("destination_id", destination_id)
    if city_input is None:
        return payload
    payload.setdefault("country", city_input.get("country"))
    payload.setdefault("travel_month", city_input.get("travel_month"))
    payload.setdefault("trip_type", city_input.get("trip_type"))
    if prefer_city_input_destination:
        payload["destination_id"] = city_input.get("destination_id")
    else:
        payload.setdefault("destination_id", city_input.get("destination_id"))
    payload.setdefault("themes", city_input.get("active_required_themes", ()))
    return payload


def _is_city_change(state: Mapping[str, Any]) -> bool:
    intent = state.get("intent")
    if not isinstance(intent, Mapping):
        return False
    modify_intent = intent.get("modify_intent")
    return isinstance(modify_intent, Mapping) and modify_intent.get("kind") == "city_change"


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
        if isinstance(clarification, Mapping):
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
    planner = state.get("planner")
    if isinstance(planner, Mapping):
        planner_output = planner.get("planner_output")
        if isinstance(planner_output, Mapping) and _is_generation_insufficient(planner_output):
            return _generation_insufficient_clarification(state, planner_output)
        if isinstance(planner_output, Mapping) and _has_weather_alternative(planner_output):
            return _weather_alternative_clarification(planner_output)
        context = planner.get("modify_context")
        if isinstance(context, Mapping):
            failed_edit = context.get("failed_edit")
            if isinstance(failed_edit, Mapping):
                return _failed_edit_clarification(failed_edit)
    return None


def _is_generation_insufficient(planner_output: Mapping[str, Any]) -> bool:
    validation = planner_output.get("validation_result")
    return (
        isinstance(validation, Mapping)
        and validation.get("planner_status_gate") == "insufficient_candidates"
    )


def _has_weather_alternative(planner_output: Mapping[str, Any]) -> bool:
    validation = planner_output.get("validation_result")
    if not isinstance(validation, Mapping):
        return False
    weather_audit = validation.get("weather_audit")
    return (
        isinstance(weather_audit, Mapping)
        and weather_audit.get("status") == "alternative_available"
        and weather_audit.get("alternative_generation_status") != "generated"
    )


def _weather_alternative_clarification(planner_output: Mapping[str, Any]) -> dict[str, Any]:
    reason_code = "weather_alternative_available"
    prompt = _prompt_text(reason_code, "날씨 영향을 줄인 대체 일정을 보여드릴까요?")
    validation = planner_output.get("validation_result")
    weather_audit = validation.get("weather_audit", {}) if isinstance(validation, Mapping) else {}
    return {
        "reason_code": reason_code,
        "prompt": prompt,
        "options": [
            {
                "option_id": "use_weather_alternative",
                "label": _label_text(reason_code, "use_weather_alternative", "날씨 대체 일정 보기"),
                "helper_text": _helper_text(reason_code, "use_weather_alternative", "실내 중심 후보로 현재 일정을 다시 구성합니다."),
                "apply": {}, "then": "weather_alternative",
            },
            {
                "option_id": "keep_primary_itinerary",
                "label": _label_text(reason_code, "keep_primary_itinerary", "현재 일정 유지"),
                "helper_text": _helper_text(reason_code, "keep_primary_itinerary", "날씨 안내만 확인하고 현재 일정을 유지합니다."),
                "apply": {}, "then": "abort",
            },
        ],
        "context": {
            "weather_audit": dict(weather_audit) if isinstance(weather_audit, Mapping) else {},
        },
        "failure_signals": [],
    }


def _generation_insufficient_clarification(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
) -> dict[str, Any]:
    reason_code = "generation_insufficient_candidates"
    current_city_id = _selected_city_id(state)
    search_other_apply: dict[str, Any] = {"destination_id": None}
    if current_city_id is not None:
        search_other_apply["disliked_city_ids"] = [current_city_id]
    return {
        "reason_code": reason_code,
        "prompt": _prompt_text(reason_code, "조건에 맞는 일정 후보가 부족합니다. 조건을 완화하거나 다른 도시를 찾아볼까요?"),
        "options": [
            {
                "option_id": "relax_generation_themes",
                "label": _label_text(reason_code, "relax_generation_themes", "테마 완화"),
                "helper_text": _helper_text(reason_code, "relax_generation_themes", "필수 테마 조건을 넓혀 같은 요청으로 다시 찾습니다."),
                "apply": {"active_required_themes": list(RELAXED_GENERATION_THEMES)},
                "then": "rerun_discovery",
            },
            {
                "option_id": "search_other_city",
                "label": _label_text(reason_code, "search_other_city", "다른 도시 찾아보기"),
                "helper_text": _helper_text(reason_code, "search_other_city", "현재 도시는 제외하고 같은 조건에 더 맞는 다른 도시를 찾습니다."),
                "apply": search_other_apply,
                "then": "rerun_discovery",
            },
        ],
        "context": {
            "selected_city_id": current_city_id,
            "validation_result": dict(planner_output.get("validation_result", {})),
        },
        "failure_signals": ["insufficient_planner_candidates"],
    }


def _selected_city_id(state: Mapping[str, Any]) -> str | None:
    selected_city = _selected_city(state)
    if selected_city is None:
        return None
    value = selected_city.get("city_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _failed_edit_clarification(failed_edit: Mapping[str, Any]) -> dict[str, Any]:
    reason_code = str(failed_edit.get("reason_code", "slot_replace_failed"))
    if reason_code == "modify_target_unresolved":
        return _target_unresolved_clarification(failed_edit, reason_code)
    return {
        "reason_code": reason_code,
        "prompt": _prompt_text(reason_code, "조건에 맞는 대체 장소를 바로 찾지 못했습니다. 조건을 조금 넓혀볼까요?"),
        "options": [
            {
                "option_id": "broaden_replace_theme",
                "label": _label_text(reason_code, "broaden_replace_theme", "조건을 넓혀 다시 찾기"),
                "helper_text": _helper_text(reason_code, "broaden_replace_theme", "테마나 분위기 조건을 완화해 대체 장소를 다시 찾습니다."),
                "apply": {}, "then": "retry_slot_replace",
            },
            {
                "option_id": "keep_current_place",
                "label": _label_text(reason_code, "keep_current_place", "현재 장소 유지"),
                "helper_text": _helper_text(reason_code, "keep_current_place", "이번 수정은 적용하지 않고 현재 일정을 유지합니다."),
                "apply": {}, "then": "abort",
            },
        ],
        "context": dict(failed_edit),
    }


def _target_unresolved_clarification(
    failed_edit: Mapping[str, Any],
    reason_code: str,
) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "prompt": _prompt_text(reason_code, "수정할 슬롯을 현재 일정에서 찾지 못했습니다. 몇 일차 몇 번째 장소를 바꿀지 다시 알려주세요."),
        "options": [
            {
                "option_id": "revise_slot_target",
                "label": _label_text(reason_code, "revise_slot_target", "수정할 장소 다시 지정"),
                "helper_text": _helper_text(reason_code, "revise_slot_target", "몇 일차 몇 번째 장소를 바꿀지 다시 입력합니다."),
                "apply": {}, "then": "abort",
            },
            {
                "option_id": "keep_current_itinerary",
                "label": _label_text(reason_code, "keep_current_itinerary", "현재 일정 유지"),
                "helper_text": _helper_text(reason_code, "keep_current_itinerary", "이번 수정은 적용하지 않고 현재 일정을 유지합니다."),
                "apply": {}, "then": "abort",
            },
        ],
        "context": dict(failed_edit),
    }


def _modify_clarification_payload(clarification: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(clarification)
    options = payload.get("options")
    if isinstance(options, list) and options:
        return payload
    reason_code = str(payload.get("reason_code", "modify_seed_theme_conflict"))
    if reason_code == "modify_target_unresolved":
        return _target_unresolved_clarification(payload, reason_code)
    payload["options"] = [
        {
            "option_id": "revise_modify_query",
            "label": _label_text(
                reason_code,
                "revise_modify_query",
                "수정 요청 다시 입력",
            ),
            "helper_text": _helper_text(
                reason_code,
                "revise_modify_query",
                "수정할 일자나 순서를 포함해 다시 요청합니다.",
            ),
            "apply": {}, "then": "abort",
        },
    ]
    return payload


def _helper_text(reason_code: str, option_id: str, default: str) -> str:
    return clarification_helper_text(reason_code, option_id, default)


def _label_text(reason_code: str, option_id: str, default: str) -> str:
    return clarification_label_text(reason_code, option_id, default)


def _prompt_text(reason_code: str, default: str) -> str:
    return clarification_prompt_text(reason_code, default)


def _planner_output(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if _has_failed_slot_replace(state):
        return None
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


def _has_failed_slot_replace(state: Mapping[str, Any]) -> bool:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return False
    context = planner.get("modify_context")
    return isinstance(context, Mapping) and isinstance(context.get("failed_edit"), Mapping)


def _extend_texts(target: list[str], value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        return
    target.extend(str(item) for item in value)
