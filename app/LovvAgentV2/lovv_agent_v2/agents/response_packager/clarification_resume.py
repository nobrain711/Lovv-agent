from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.response_packager.weather_alternative_resume import (
    weather_alternative_response_update,
)
from lovv_agent_v2.agents.response_packager.weather_primary_resume import (
    primary_weather_response_update,
)
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def response_resume_update(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
    resume_value: Any,
) -> dict[str, Any]:
    if _is_corrected_create_resume(resume_value):
        return _corrected_create_update(resume_value)
    action = _resolved_action(response, resume_value)
    match action["then"]:
        case "rerun_discovery" | "anchor":
            return _rerun_update(state, action)
        case "retry_slot_replace":
            return _retry_slot_replace_update(state, action)
        case "weather_alternative":
            return weather_alternative_response_update(state, response, action)
        case "abort":
            if action["option_id"] == "keep_primary_itinerary":
                return primary_weather_response_update(state, response, action)
            next_response = dict(response)
            next_response["clarification_resume"] = action
            return {"response": next_response}
        case _:
            raise SchemaValidationError("clarification option.then is invalid")


def _resolved_action(response: Mapping[str, Any], resume_value: Any) -> dict[str, Any]:
    option_id = _resume_option_id(resume_value)
    clarification = _mapping(response.get("response_payload", {}).get("clarification"))
    for option in _options(clarification):
        if _text(option.get("optionId", option.get("option_id"))) == option_id:
            return {
                "option_id": option_id,
                "label": _text(option.get("label")),
                "reason_code": _text(clarification.get("reasonCode", clarification.get("reason_code"))),
                "apply": _normalized_apply(_mapping(option.get("apply"))),
                "then": _text(option.get("then")),
            }
    raise SchemaValidationError("selected clarification option was not found")


def _rerun_update(state: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    city_input = _patched_city_input(state, _mapping(action.get("apply")))
    next_intent = dict(_mapping(state.get("intent", {})))
    next_intent["intent_type"] = "create"
    next_intent.pop("trip_intent", None)
    next_intent["city_select_input"] = city_input
    next_intent["clarification_resume"] = dict(action)
    return {
        "intent": next_intent,
        "festival_gate": _synthetic_festival_gate(action, city_input),
        "city_select": {},
        "planner": {},
        "response": {},
    }


def _patched_city_input(
    state: Mapping[str, Any],
    apply_payload: Mapping[str, Any],
) -> dict[str, Any]:
    intent = _mapping(state.get("intent", {}))
    city_input = dict(_mapping(intent.get("city_select_input")))
    if "include_festivals" in apply_payload:
        city_input["include_festivals"] = apply_payload["include_festivals"]
    if "destination_id" in apply_payload:
        city_input["destination_id"] = apply_payload["destination_id"]
    if apply_payload.get("destination_label") is not None:
        city_input["destination_label"] = apply_payload["destination_label"]
    if apply_payload.get("travel_month") is not None:
        city_input["travel_month"] = apply_payload["travel_month"]
    if apply_payload.get("active_required_themes") is not None:
        city_input["active_required_themes"] = list(apply_payload["active_required_themes"])
    if apply_payload.get("disliked_city_ids") is not None:
        city_input["disliked_city_ids"] = list(apply_payload["disliked_city_ids"])
    city_input["execution_mode"] = (
        "anchored_place_search" if city_input.get("destination_id") else "city_discovery"
    )
    normalized = CitySelectInput.from_mapping(city_input).to_dict()
    normalized["active_required_themes"] = list(normalized["active_required_themes"])
    if apply_payload.get("festival_theme_agnostic") is not None:
        normalized["festival_theme_agnostic"] = apply_payload["festival_theme_agnostic"]
    return normalized


def _synthetic_festival_gate(
    action: Mapping[str, Any],
    city_input: Mapping[str, Any],
) -> dict[str, Any]:
    apply_payload = _mapping(action.get("apply"))
    if not (
        action.get("then") == "anchor"
        and apply_payload.get("include_festivals") is True
        and apply_payload.get("festival_id") is not None
    ):
        return {}
    destination_id = _text(city_input.get("destination_id"))
    if destination_id is None:
        return {}
    festival = {
        "festival_id": apply_payload["festival_id"],
        "name": apply_payload.get("festival_label"),
        "date_status": "tentative" if apply_payload.get("accepted_festival_risk") else "confirmed",
    }
    verified_city = {
        "city_id": destination_id,
        "city_name": apply_payload.get("destination_label"),
        "festivals": [festival],
    }
    return {
        "result": {
            "status": "ok",
            "allowed_city_ids": [destination_id],
            "verified_festival_cities": [verified_city],
            "audit": {"clarification_resume": dict(action)},
        },
        "allowed_city_ids": [destination_id],
        "verified_festival_cities": [verified_city],
        "clarification": None,
        "audit": {"clarification_resume": dict(action)},
    }


def _retry_slot_replace_update(
    state: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    intent = dict(_mapping(state.get("intent", {})))
    modify_intent = _broadened_modify_intent(
        _mapping(intent.get("modify_intent")),
        state,
        action,
    )
    intent["intent_type"] = "modification"
    intent["modify_intent"] = modify_intent
    return {
        "intent": intent,
        "planner": _planner_without_failed_edit(state),
        "response": {},
    }


def _broadened_modify_intent(
    modify_intent: Mapping[str, Any],
    state: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    failed_target = _failed_target(state)
    edit_ops = [
        _broadened_operation(option, failed_target)
        for option in _edit_ops(modify_intent)
    ]
    return {
        **dict(modify_intent),
        "status": "ok",
        "kind": "slot_replace",
        "routing_hint": "planner_apply_edit",
        "edit_ops": edit_ops,
        "clarification": None,
        "clarification_resume": dict(action),
    }


def _broadened_operation(
    operation: Mapping[str, Any],
    failed_target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if failed_target is not None and not _same_slot(_mapping(operation.get("target")), failed_target):
        return dict(operation)
    condition = dict(_mapping(operation.get("condition")))
    condition.pop("theme", None)
    condition["theme_relaxed"] = True
    seed_policy = dict(_mapping(operation.get("seed_policy")))
    if seed_policy.get("policy") == "same_theme_required":
        seed_policy["previous_policy"] = "same_theme_required"
        seed_policy["policy"] = "theme_relaxed"
    return {
        **dict(operation),
        "condition": condition,
        "seed_policy": seed_policy,
    }


def _planner_without_failed_edit(state: Mapping[str, Any]) -> dict[str, Any]:
    planner = dict(_mapping(state.get("planner", {})))
    context = dict(_mapping(planner.get("modify_context", {})))
    context.pop("failed_edit", None)
    context.pop("failed_edits", None)
    context["clarification_resume"] = {"option_id": "broaden_replace_theme"}
    planner["modify_context"] = context
    return planner


def _failed_target(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    planner = _mapping(state.get("planner", {}))
    context = _mapping(planner.get("modify_context", {}))
    failed_edit = context.get("failed_edit")
    if not isinstance(failed_edit, Mapping):
        return None
    target = failed_edit.get("target")
    return target if isinstance(target, Mapping) else None


def _edit_ops(modify_intent: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    edit_ops = modify_intent.get("edit_ops")
    if not isinstance(edit_ops, Sequence) or isinstance(edit_ops, (str, bytes)):
        return ()
    return tuple(option for option in edit_ops if isinstance(option, Mapping))


def _same_slot(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("day") == right.get("day") and left.get("order") == right.get("order")


def _normalized_apply(payload: Mapping[str, Any]) -> dict[str, Any]:
    field_pairs = (
        ("include_festivals", ("include_festivals", "includeFestivals")),
        ("destination_id", ("destination_id", "destinationId")),
        ("destination_label", ("destination_label", "destinationLabel")),
        ("festival_id", ("festival_id", "festivalId")),
        ("festival_label", ("festival_label", "festivalLabel")),
        ("allow_tentative_festivals", ("allow_tentative_festivals", "allowTentativeFestivals")),
        ("accepted_festival_risk", ("accepted_festival_risk", "acceptedFestivalRisk")),
        ("travel_month", ("travel_month", "travelMonth")),
        ("active_required_themes", ("active_required_themes", "activeRequiredThemes")),
        ("disliked_city_ids", ("disliked_city_ids", "dislikedCityIds")),
        ("festival_theme_agnostic", ("festival_theme_agnostic", "festivalThemeAgnostic")),
    )
    normalized: dict[str, Any] = {}
    for target, keys in field_pairs:
        for key in keys:
            if key in payload:
                if payload[key] is not None or target == "destination_id":
                    normalized[target] = payload[key]
                break
    return normalized


def _is_corrected_create_resume(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    entry_type = _text(value.get("entryType", value.get("entry_type")))
    return entry_type == "clarify" and _has_create_request_fields(value)


def _corrected_create_update(value: Any) -> dict[str, Any]:
    request = dict(_mapping(value))
    request["entryType"] = "create"
    update = intent_node({"request": request})
    update["request"] = request
    return update


def _has_create_request_fields(request: Mapping[str, Any]) -> bool:
    required_fields = ("country", "travelMonth", "tripType", "includeFestivals")
    snake_fields = ("country", "travel_month", "trip_type", "include_festivals")
    has_core = all(key in request for key in required_fields) or all(
        key in request for key in snake_fields
    )
    has_query = any(
        key in request
        for key in ("rawQuery", "raw_query", "naturalLanguageQuery")
    )
    return has_core and has_query


def _resume_option_id(value: Any) -> str:
    if isinstance(value, str):
        return _required_text(value)
    if isinstance(value, Mapping):
        return _required_text(
            value.get(
                "selectedOptionId",
                value.get("selected_option_id", value.get("optionId", value.get("option_id"))),
            ),
        )
    raise SchemaValidationError("clarification resume must include optionId")


def _options(clarification: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    options = clarification.get("options")
    if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
        raise SchemaValidationError("clarification.options must be a sequence")
    return tuple(_mapping(option) for option in options)


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("clarification resume payload must be a mapping")
    return value


def _required_text(value: Any) -> str:
    text = _text(value)
    if text is None:
        raise SchemaValidationError("clarification optionId must be a non-empty string")
    return text


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["response_resume_update"]
