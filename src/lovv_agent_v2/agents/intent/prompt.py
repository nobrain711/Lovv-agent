from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from lovv_agent_v2.infra.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent_v2.agents.intent.parser import theme_labels
from lovv_agent_v2.agents.intent.prompts.intent_normalization import INTENT_PROMPT_TEXT
from lovv_agent_v2.agents.intent.prompt_regions import canonical_prompt_region_updates
from lovv_agent_v2.agents.intent.prompt_schema import (
    INTENT_PROMPT_OUTPUT_SCHEMA,
    INTENT_PROMPT_SCHEMA_NAME,
)
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError

_TUPLE_FIELDS: Final = (
    "preferred_theme_ids",
    "disliked_theme_ids",
    "preferred_region_spans",
    "disliked_region_spans",
    "contradiction_reasons",
)
_CONGESTION_SIGNAL_KEYWORDS: Final = (
    "조용",
    "한적",
    "사람 적",
    "사람 많",
    "피하",
    "북적",
    "활기",
    "생동감",
    "축제",
    "야간",
)


@dataclass(frozen=True, slots=True)
class PromptIntentResult:
    city_select_input: dict[str, Any]
    intent_updates: dict[str, Any]


def prompt_intent_from_request(
    *,
    runtime: RuntimeInvoker,
    request: Mapping[str, Any],
    retry_limit: int,
) -> PromptIntentResult | None:
    converse_request = build_intent_prompt_request(request)
    result = invoke_structured_output(
        runtime=runtime,
        request=converse_request,
        retry_limit=retry_limit,
        validator=lambda payload: validate_intent_prompt_output(
            payload,
            request=request,
        ),
    )
    return result.value if isinstance(result.value, PromptIntentResult) else None


def build_intent_prompt_request(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "task": "Extract Lovv V2 intent fields from this request.",
        "api_request": dict(request),
    }
    request_payload = build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
            },
        ],
        system=[{"text": INTENT_PROMPT_TEXT}],
        schema_name=INTENT_PROMPT_SCHEMA_NAME,
        schema=INTENT_PROMPT_OUTPUT_SCHEMA,
        schema_description="Lovv V2 prompt-based intent output",
        reasoning_effort="low",
    )
    request_payload["inferenceConfig"] = {"maxTokens": 512, "temperature": 0}
    return request_payload


def validate_intent_prompt_output(
    payload: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
) -> PromptIntentResult:
    normalized_payload = dict(payload)
    value = normalized_payload.get("clarifying_question")
    if isinstance(value, str) and not value.strip():
        normalized_payload["clarifying_question"] = None
    _normalize_soft_congestion(normalized_payload)
    city_input_payload = _city_select_input_from_request(
        payload if request is None else request,
    )
    preferred_theme_ids = _string_tuple(
        normalized_payload.get("preferred_theme_ids", ()),
        "preferred_theme_ids",
    )
    if not city_input_payload["active_required_themes"] and preferred_theme_ids:
        city_input_payload["active_required_themes"] = theme_labels(preferred_theme_ids)
    city_input_payload.update(
        {
            "cleaned_raw_query": normalized_payload["cleaned_raw_query"],
            "soft_preference_query": normalized_payload["soft_preference_query"],
            "unsupported_conditions": normalized_payload["unsupported_conditions"],
            "congestion_pref": normalized_payload["congestion_pref"],
            "transport_pref": normalized_payload["transport_pref"],
        },
    )
    updates: dict[str, Any] = {
        "intent_extraction_mode": "prompt_structured_output",
    }
    for field_name in _TUPLE_FIELDS:
        updates[field_name] = (
            preferred_theme_ids
            if field_name == "preferred_theme_ids"
            else _string_tuple(normalized_payload.get(field_name, ()), field_name)
        )
    updates.update(
        canonical_prompt_region_updates(
            raw_query=_request_raw_query({} if request is None else request),
            preferred_spans=updates["preferred_region_spans"],
            disliked_spans=updates["disliked_region_spans"],
        ),
    )
    updates["needs_clarification"] = _bool(normalized_payload.get("needs_clarification"))
    updates["clarifying_question"] = _optional_text(
        normalized_payload.get("clarifying_question"),
    )
    city_input_payload.update(
        {
            "preferred_theme_ids": updates["preferred_theme_ids"],
            "disliked_theme_ids": updates["disliked_theme_ids"],
            "preferred_region_ids": updates.get("preferred_region_ids", ()),
            "disliked_region_ids": updates.get("disliked_region_ids", ()),
            "preferred_region_spans": updates["preferred_region_spans"],
            "disliked_region_spans": updates["disliked_region_spans"],
            "unresolved_region_spans": updates.get("unresolved_region_spans", ()),
            "preferred_region_names": updates.get("preferred_region_names", ()),
            "disliked_region_names": updates.get("disliked_region_names", ()),
            "needs_clarification": updates["needs_clarification"],
            "clarifying_question": updates["clarifying_question"],
            "contradiction_reasons": updates["contradiction_reasons"],
        },
    )
    city_input = CitySelectInput.from_mapping(city_input_payload).to_dict()
    city_input["active_required_themes"] = list(city_input["active_required_themes"])
    return PromptIntentResult(city_select_input=city_input, intent_updates=updates)


def _city_select_input_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
    themes = request.get("themes", request.get("active_required_themes", ()))
    destination_id = request.get("destination_id", request.get("destinationId"))
    include_festivals = _first_present(
        request,
        "include_festivals",
        "includeFestivals",
    )
    return {
        "country": _first_present(request, "country"),
        "travel_month": _first_present(request, "travel_month", "travelMonth"),
        "travel_year": _first_present(request, "travel_year", "travelYear"),
        "trip_type": _first_present(request, "trip_type", "tripType"),
        "active_required_themes": themes,
        "include_festivals": include_festivals,
        "destination_id": destination_id,
        "city_key": request.get("city_key", request.get("cityKey")),
        "ddb_pk": request.get("ddb_pk", request.get("ddbPk")),
        "user_location": request.get("user_location", request.get("userLocation")),
        "execution_mode": request.get(
            "execution_mode",
            request.get(
                "executionMode",
                _execution_mode(
                    destination_id=destination_id,
                    include_festivals=include_festivals,
                ),
            ),
        ),
    }


def _execution_mode(*, destination_id: Any, include_festivals: Any) -> str:
    if isinstance(destination_id, str) and destination_id.strip():
        return "anchored_place_search"
    if include_festivals is True:
        return "festival_seeded_city_discovery"
    return "city_discovery"


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
    return value if isinstance(value, str) else ""


def _normalize_soft_congestion(payload: dict[str, Any]) -> None:
    raw_query = payload.get("cleaned_raw_query")
    soft_query = payload.get("soft_preference_query")
    raw_text = raw_query if isinstance(raw_query, str) else ""
    soft_text = soft_query if isinstance(soft_query, str) else ""
    if (
        payload.get("congestion_pref") != "neutral"
        and not any(keyword in raw_text for keyword in _CONGESTION_SIGNAL_KEYWORDS)
        and any(keyword in soft_text for keyword in _CONGESTION_SIGNAL_KEYWORDS)
    ):
        payload["congestion_pref"] = "neutral"


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a list")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must contain non-empty strings")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "clarifying_question")


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SchemaValidationError("needs_clarification must be a boolean")
    return value
