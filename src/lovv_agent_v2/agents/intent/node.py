from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.clarify_parser import build_clarify_intent
from lovv_agent_v2.agents.intent.clarifications import (
    PREFERENCE_CLARIFYING_QUESTION,
    set_contradiction_clarification,
    set_unsupported_region_clarification,
)
from lovv_agent_v2.agents.intent.modify_dispatch import resolve_modify_intent
from lovv_agent_v2.agents.intent.modify_reanchor import modify_state_update
from lovv_agent_v2.agents.intent.prompt import PromptIntentResult, prompt_intent_from_request
from lovv_agent_v2.agents.intent.parser import (
    IntentPreferenceResult,
    clean_preference_query,
    parse_initial_query,
)
from lovv_agent_v2.agents.intent.request_shape import entry_type, has_create_request_fields
from lovv_agent_v2.tools.runtime_extractors import intent_prompt_runtime_from_state
from lovv_agent_v2.agents.intent.validator import validate_preference_sets
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.city_identity import enrich_city_select_identity
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def intent_node(state: UnifiedAgentState) -> dict[str, Any]:
    intent = _intent_payload(state)
    request = state.get("request")
    if isinstance(request, Mapping):
        match entry_type(request):
            case "clarify":
                if has_create_request_fields(request):
                    pass
                else:
                    return {"intent": build_clarify_intent(request, state)}
            case "modify":
                return modify_state_update(intent, resolve_modify_intent(state, request), state)
            case "confirm":
                return {"intent": _confirm_intent(request)}
            case "create":
                pass
            case unreachable:
                _ = unreachable
    fresh_create_request = isinstance(request, Mapping) and entry_type(request) in {
        "create",
        "clarify",
    }
    existing_input = None if fresh_create_request else _existing_city_select_input(intent)
    prompt_result = _prompt_result(state, request) if existing_input is None else None
    city_input = (
        prompt_result.city_select_input
        if prompt_result is not None
        else _city_select_input({} if fresh_create_request else intent, request)
    )
    enriched_input = enrich_city_select_identity(city_input)
    normalized_input = CitySelectInput.from_mapping(enriched_input).to_dict()
    normalized_input["active_required_themes"] = list(
        normalized_input["active_required_themes"],
    )
    normalized_input["cleaned_raw_query"] = clean_preference_query(
        normalized_input["cleaned_raw_query"],
    )
    next_intent = {} if fresh_create_request else dict(intent)
    if prompt_result is not None:
        next_intent.update(prompt_result.intent_updates)
        _reconcile_preference_fields(next_intent)
    next_intent.setdefault("intent_type", "create")
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
    next_intent.setdefault(
        "intent_extraction_mode",
        "provided" if existing_input is not None else "code_parser",
    )
    if prompt_result is None and existing_input is None and isinstance(request, Mapping):
        _apply_preference_result(
            next_intent, parse_initial_query(_request_raw_query(request))
        )
    set_unsupported_region_clarification(
        next_intent,
        request if isinstance(request, Mapping) else None,
        normalized_input,
    )
    if fresh_create_request:
        return {
            "intent": next_intent,
            "festival_gate": {},
            "city_select": {},
            "planner": {},
            "response": {},
            "routing": {},
        }
    return {"intent": next_intent}


def _intent_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        return dict(intent)
    return {}


def _confirm_intent(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "intent_type": "confirm",
        "status": "ok",
        "thread_id": _text_or_none(request.get("threadId", request.get("thread_id"))),
        "recommendation_id": _text_or_none(
            request.get("recommendationId", request.get("recommendation_id")),
        ),
        "itinerary_revision": _text_or_none(
            request.get("itineraryRevision", request.get("itinerary_revision")),
        ),
    }


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _city_select_input(
    intent: Mapping[str, Any],
    request: Any,
) -> Mapping[str, Any]:
    value = _existing_city_select_input(intent)
    if value is not None:
        return value
    if isinstance(request, Mapping):
        return _city_select_input_from_request(request)
    raise SchemaValidationError("intent.city_select_input or state.request is required")


def _existing_city_select_input(intent: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = intent.get("city_select_input")
    return value if isinstance(value, Mapping) else None


def _prompt_result(
    state: Mapping[str, Any],
    request: Any,
) -> PromptIntentResult | None:
    if not isinstance(request, Mapping):
        return None
    prompt_runtime = intent_prompt_runtime_from_state(state)
    if prompt_runtime.runtime is None:
        return None
    return prompt_intent_from_request(
        runtime=prompt_runtime.runtime,
        request=request,
        retry_limit=prompt_runtime.schema_retry_limit,
    )


def _city_select_input_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    preference_result = parse_initial_query(_request_raw_query(request))
    request_themes = request.get("themes", request.get("active_required_themes", ()))
    themes = request_themes or preference_result.active_theme_labels
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
        "cleaned_raw_query": preference_result.cleaned_raw_query,
        "soft_preference_query": "",
        "unsupported_conditions": request.get("unsupported_conditions", ()),
        "destination_id": request.get("destination_id", request.get("destinationId")),
        "city_key": request.get("city_key", request.get("cityKey")),
        "ddb_pk": request.get("ddb_pk", request.get("ddbPk")),
        "user_location": request.get("user_location", request.get("userLocation")),
        "execution_mode": request.get("execution_mode", "city_discovery"),
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
        "preferred_theme_ids": preference_result.preferred_theme_ids,
        "disliked_theme_ids": preference_result.disliked_theme_ids,
        "preferred_region_ids": preference_result.preferred_region_ids,
        "disliked_region_ids": preference_result.disliked_region_ids,
        "preferred_region_spans": preference_result.preferred_region_spans,
        "disliked_region_spans": preference_result.disliked_region_spans,
        "unresolved_region_spans": preference_result.unresolved_region_spans,
        "preferred_region_names": preference_result.preferred_region_names,
        "disliked_region_names": preference_result.disliked_region_names,
        "needs_clarification": preference_result.needs_clarification,
        "clarifying_question": preference_result.clarifying_question,
        "contradiction_reasons": preference_result.contradiction_reasons,
    }


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise SchemaValidationError(f"missing required request field: {keys[0]}")


def _request_raw_query(request: Mapping[str, Any]) -> str:
    value = request.get(
        "raw_query",
        request.get("rawQuery", request.get("naturalLanguageQuery", "")),
    )
    if isinstance(value, str):
        return value
    return ""


def _apply_preference_result(
    intent: dict[str, Any],
    preference_result: IntentPreferenceResult,
) -> None:
    intent.setdefault("preferred_theme_ids", preference_result.preferred_theme_ids)
    intent.setdefault("disliked_theme_ids", preference_result.disliked_theme_ids)
    intent.setdefault("preferred_region_ids", preference_result.preferred_region_ids)
    intent.setdefault("disliked_region_ids", preference_result.disliked_region_ids)
    intent.setdefault("preferred_region_spans", preference_result.preferred_region_spans)
    intent.setdefault("disliked_region_spans", preference_result.disliked_region_spans)
    intent.setdefault("unresolved_region_spans", preference_result.unresolved_region_spans)
    intent.setdefault(
        "preferred_region_names", preference_result.preferred_region_names
    )
    intent.setdefault("disliked_region_names", preference_result.disliked_region_names)
    intent.setdefault("needs_clarification", preference_result.needs_clarification)
    intent.setdefault("clarifying_question", preference_result.clarifying_question)
    intent.setdefault("contradiction_reasons", preference_result.contradiction_reasons)
    set_contradiction_clarification(intent)


def _reconcile_preference_fields(intent: dict[str, Any]) -> None:
    validation = validate_preference_sets(
        preferred_theme_ids=_text_tuple(intent.get("preferred_theme_ids", ())),
        disliked_theme_ids=_text_tuple(intent.get("disliked_theme_ids", ())),
        preferred_region_ids=_text_tuple(intent.get("preferred_region_ids", ())),
        disliked_region_ids=_text_tuple(intent.get("disliked_region_ids", ())),
    )
    if not validation.needs_clarification:
        intent.setdefault("contradiction_reasons", ())
        return
    intent["needs_clarification"] = True
    intent["clarifying_question"] = PREFERENCE_CLARIFYING_QUESTION
    intent["contradiction_reasons"] = validation.contradiction_reasons
    set_contradiction_clarification(intent)


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))
