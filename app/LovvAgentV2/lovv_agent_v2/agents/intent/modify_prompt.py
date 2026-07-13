from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from lovv_agent_v2.agents.intent.modify_prompt_normalizer import (
    normalize_prompt_city_change,
    normalize_prompt_edit_ops,
)
from lovv_agent_v2.agents.intent.modify_day_regenerate import normalize_prompt_day_regenerate
from lovv_agent_v2.agents.intent.prompts.modify_intent import MODIFY_PROMPT_TEXT
from lovv_agent_v2.infra.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent_v2.models.schemas import SchemaValidationError

MODIFY_PROMPT_SCHEMA_NAME: Final = "lovv_v2_modify_intent_output"

MODIFY_PROMPT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "kind",
        "edit_ops",
        "city_change",
        "clarification",
        "unsupported_reasons",
        "routing_hint",
        "audit",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ok", "needs_clarification", "unsupported"],
        },
        "kind": {"type": "string", "enum": ["slot_replace", "day_regenerate", "city_change", "backlog"]},
        "edit_ops": {"type": "array", "items": {"type": "object"}},
        "day_regenerate": {"type": ["object", "null"]},
        "city_change": {"type": ["object", "null"]},
        "clarification": {"type": ["object", "null"]},
        "unsupported_reasons": {"type": "array", "items": {"type": "string"}},
        "routing_hint": {"type": "string"},
        "audit": {"type": "object"},
    },
}


def prompt_modify_intent_from_request(
    *,
    runtime: RuntimeInvoker,
    request: Mapping[str, Any],
    retry_limit: int,
) -> dict[str, Any] | None:
    result = invoke_structured_output(
        runtime=runtime,
        request=build_modify_prompt_request(request),
        retry_limit=retry_limit,
        validator=lambda payload: validate_modify_prompt_output(
            payload,
            request=request,
        ),
    )
    return result.value if isinstance(result.value, dict) else None


def build_modify_prompt_request(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "task": "Parse Lovv V2 modify_intent from this request.",
        "modify_request": dict(request),
        "current_order": request.get("currentOrder", request.get("current_order", [])),
    }
    request_payload = build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
            },
        ],
        system=[{"text": MODIFY_PROMPT_TEXT}],
        schema_name=MODIFY_PROMPT_SCHEMA_NAME,
        schema=MODIFY_PROMPT_OUTPUT_SCHEMA,
        schema_description="Lovv V2 modify intent output",
        reasoning_effort="low",
    )
    request_payload["inferenceConfig"] = {"maxTokens": 2048, "temperature": 0}
    return request_payload


def validate_modify_prompt_output(
    payload: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    raw_query = _required_text(
        request.get("rawModifyQuery", request.get("raw_modify_query")),
        "raw_modify_query",
    )
    status = _choice(payload.get("status"), ("ok", "needs_clarification", "unsupported"), "status")
    kind = _choice(payload.get("kind"), ("slot_replace", "day_regenerate", "city_change", "backlog"), "kind")
    day_regenerate = normalize_prompt_day_regenerate(payload.get("day_regenerate"), request)
    city_change = normalize_prompt_city_change(
        _mapping_or_none(payload.get("city_change"), "city_change"),
        request,
    )
    result = {
        "intent_type": "modification",
        "status": status,
        "thread_id": _required_text(request.get("threadId", request.get("thread_id")), "thread_id"),
        "itinerary_revision": _required_text(
            request.get("itineraryRevision", request.get("itinerary_revision")),
            "itinerary_revision",
        ),
        "destination_id": _optional_text(
            request.get("destinationId", request.get("destination_id")),
        ),
        "raw_modify_query": raw_query,
        "kind": kind,
        "edit_ops": normalize_prompt_edit_ops(
            _list(payload.get("edit_ops"), "edit_ops"),
            request,
        ),
        "day_regenerate": day_regenerate,
        "city_change": city_change,
        "clarification": _clarification(
            payload.get("clarification"),
            status=status,
            raw_query=raw_query,
        ),
        "unsupported_reasons": _string_list(
            payload.get("unsupported_reasons"),
            "unsupported_reasons",
        ),
        "routing_hint": _routing_hint(
            status=status,
            kind=kind,
            value=payload.get("routing_hint"),
            city_change=city_change,
        ),
        "audit": dict(_mapping(payload.get("audit"), "audit")),
    }
    _validate_status_shape(result)
    return result


def _validate_status_shape(result: Mapping[str, Any]) -> None:
    status = result["status"]
    kind = result["kind"]
    if status == "ok" and kind == "slot_replace" and not result["edit_ops"]:
        raise SchemaValidationError("slot_replace modify intent requires edit_ops")
    if status == "ok" and kind == "day_regenerate" and result["day_regenerate"] is None:
        raise SchemaValidationError("day_regenerate modify intent requires day_regenerate")
    if status == "ok" and kind == "city_change" and result["city_change"] is None:
        raise SchemaValidationError("city_change modify intent requires city_change")
    if status == "unsupported" and not result["unsupported_reasons"]:
        raise SchemaValidationError("unsupported modify intent requires unsupported_reasons")
    if status == "needs_clarification" and result["clarification"] is None:
        raise SchemaValidationError("clarification modify intent requires clarification")


def _routing_hint(
    *,
    status: str,
    kind: str,
    value: Any,
    city_change: Mapping[str, Any] | None,
) -> str:
    if status == "needs_clarification":
        return "response_packager_wait_user"
    if status == "unsupported":
        return "response_packager_notice"
    if kind == "city_change":
        if city_change is not None and _optional_text(city_change.get("target_city_id")) is not None:
            return "planner_direct_anchor"
        if city_change is not None or value == "city_select_rediscovery":
            return "city_select_rediscovery"
        return "planner_direct_anchor"
    if kind == "slot_replace":
        return "planner_apply_edit"
    if kind == "day_regenerate":
        return "planner_apply_edit"
    return _required_text(value, "routing_hint")


def _clarification(value: Any, *, status: str, raw_query: str) -> dict[str, Any] | None:
    if status != "needs_clarification":
        return _mapping_or_none(value, "clarification")
    payload = dict(_mapping(value, "clarification"))
    if isinstance(payload.get("reason_code"), str):
        return payload
    text = " ".join(str(item) for item in (payload.get("reason"), payload.get("suggestion"), raw_query))
    return {
        "reason_code": _fallback_reason_code(text),
        "prompt": _fallback_prompt(payload),
        "options": list(payload.get("options", []))
        if isinstance(payload.get("options"), list)
        else [],
    }


def _fallback_reason_code(text: str) -> str:
    lowered = text.lower()
    if "seed" in lowered or "핵심" in text:
        return "modify_seed_theme_conflict"
    if "ambiguous" in lowered or "여러" in text:
        return "modify_target_ambiguous"
    return "modify_target_unresolved"


def _fallback_prompt(payload: Mapping[str, Any]) -> str:
    for key in ("prompt", "suggestion", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "수정 조건을 다시 확인해주세요."


def _choice(value: Any, choices: tuple[str, ...], field_name: str) -> str:
    text = _required_text(value, field_name)
    if text not in choices:
        raise SchemaValidationError(f"{field_name} is invalid")
    return text


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be an object")
    return value


def _mapping_or_none(value: Any, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(_mapping(value, field_name))


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    return list(value)


def _string_list(value: Any, field_name: str) -> list[str]:
    values = _list(value, field_name)
    return [_required_text(item, field_name) for item in values]


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be non-empty")
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
