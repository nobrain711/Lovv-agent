"""AgentCore Runtime HTTP entrypoint for V2."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from lovv_agent_v2.agentcore_io import decode_json_if_needed as _decode_json_if_needed
from lovv_agent_v2.agentcore_io import (
    extract_actor_id,
    extract_request_id,
    extract_resume_value,
    extract_thread_id,
    interrupt_response,
)
from lovv_agent_v2.agents.profile.evidence import (
    InMemoryProfileEvidenceCache,
    ProfileEvidenceResolver,
)
from lovv_agent_v2.agents.intent.parser import THEME_ID_TO_LABEL
from lovv_agent_v2.core.trace_context import TraceContext, with_trace_context
from lovv_agent_v2.harness import LovvLangGraphV2Harness, build_live_harness


_REQUEST_FIELD_MARKERS = frozenset(
    {
        "entryType",
        "country",
        "travelMonth",
        "tripType",
        "themes",
        "includeFestivals",
    },
)
_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _cached_live_harness() -> LovvLangGraphV2Harness:
    """Build the live harness once per warm AgentCore runtime instance."""

    return build_live_harness()


@lru_cache(maxsize=1)
def _cached_profile_evidence_resolver() -> ProfileEvidenceResolver:
    return ProfileEvidenceResolver(
        cache=InMemoryProfileEvidenceCache(ttl_seconds=900),
        tool=None,
    )


def handle_v2_invocation(event: Any, context: Any | None = None) -> dict[str, Any]:
    """Invoke the V2 recommendation graph from an AgentCore payload."""

    request_id = extract_request_id(event)
    thread_id = extract_thread_id(event, fallback=request_id)
    actor_id = extract_actor_id(event) or thread_id
    checkpoint_actor_id = thread_id
    resume_value = extract_resume_value(event)
    clarify_resume = _clarify_resume_value(event) if resume_value is None else None
    payload = (
        Command(resume=resume_value if resume_value is not None else clarify_resume)
        if resume_value is not None or clarify_resume is not None
        else extract_graph_payload(event, request_id=request_id)
    )
    if isinstance(payload, dict):
        payload = with_trace_context(
            payload,
            TraceContext(
                request_id=request_id,
                thread_id=thread_id,
                actor_id=actor_id,
            ),
        )
    if resume_value is None and clarify_resume is None:
        payload = _payload_with_profile_evidence(
            payload,
            actor_id=actor_id,
            thread_id=thread_id,
        )

    # Requirement 2: thread_id and actor_id plumbing
    graph_config = {
        "configurable": {
            "thread_id": thread_id,
            "actor_id": checkpoint_actor_id,
        }
    }
    _emit_entrypoint_route(
        {
            "logType": "AGENT_ENTRYPOINT_ROUTE",
            "requestId": request_id,
            "threadId": thread_id,
            "actorId": actor_id,
            "checkpointActorId": checkpoint_actor_id,
            "payloadKind": "resume" if isinstance(payload, Command) else "state",
            "hasResumeValue": resume_value is not None,
            "hasClarifyResume": clarify_resume is not None,
        },
    )
    result = _cached_live_harness().invoke(
        payload,
        request_id=request_id,
        graph_config=graph_config,
    )
    interrupted = interrupt_response(result)
    if interrupted is not None:
        return interrupted
    response = result.get("response") if isinstance(result, Mapping) else None
    if not isinstance(response, Mapping) or not isinstance(
        response.get("response_payload"),
        Mapping,
    ):
        raise ValueError("V2 graph did not produce response payload")
    return dict(response["response_payload"])


def _payload_with_profile_evidence(
    payload: dict[str, Any],
    *,
    actor_id: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    try:
        return _cached_profile_evidence_resolver().enrich_graph_payload(
            payload,
            actor_id=actor_id,
            thread_id=thread_id,
        )
    except Exception:  # noqa: BLE001
        enriched = dict(payload)
        profile_value = enriched.get("profile", {})
        profile = dict(profile_value) if isinstance(profile_value, Mapping) else {}
        profile["saved_itinerary_evidence_audit"] = {
            "cache_status": "bypassed",
            "fallback_reason": "resolver_failed",
        }
        enriched["profile"] = profile
        return enriched


def _clarify_resume_value(event: Any) -> dict[str, Any] | None:
    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    for payload in _clarify_payload_candidates(decoded):
        option_resume = _clarify_option_resume(payload)
        if option_resume is not None:
            return option_resume
        return extract_recommendation_payload(payload)
    return None


def _clarify_payload_candidates(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    candidates = [payload]
    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in payload:
            continue
        nested = _decode_json_if_needed(payload[key])
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return tuple(candidate for candidate in candidates if _entry_type(candidate) == "clarify")


def _clarify_option_resume(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    selected_option = _text_or_none(
        payload.get("selectedOptionId", payload.get("selected_option_id")),
    )
    if selected_option is not None:
        return {"selectedOptionId": selected_option}
    option_id = _text_or_none(payload.get("optionId", payload.get("option_id")))
    return {"optionId": option_id} if option_id is not None else None


def extract_graph_payload(event: Any, *, request_id: str | None = None) -> dict[str, Any]:
    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        raise ValueError("AgentCore invocation payload must be an object")
    direct = _graph_payload_from_mapping(decoded, request_id=request_id)
    if direct is not None:
        return direct

    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in decoded:
            continue
        nested = _decode_json_if_needed(decoded[key])
        if not isinstance(nested, Mapping):
            continue
        payload = _graph_payload_from_mapping(nested, request_id=request_id)
        if payload is not None:
            return payload

    raise ValueError(
        "AgentCore invocation must contain a /recommendations request payload",
    )


def extract_recommendation_payload(event: Any) -> dict[str, Any]:
    """Normalize supported AgentCore/HTTP wrappers into the API request object."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        raise ValueError("AgentCore invocation payload must be an object")

    if _looks_like_recommendation_request(decoded):
        return dict(decoded)

    for key in ("payload", "input", "request", "body", "prompt"):
        if key not in decoded:
            continue
        nested = _decode_json_if_needed(decoded[key])
        if isinstance(nested, Mapping) and _looks_like_recommendation_request(nested):
            return dict(nested)

    raise ValueError(
        "AgentCore invocation must contain a /recommendations request payload",
    )


def _looks_like_recommendation_request(payload: Mapping[str, Any]) -> bool:
    """Return whether a mapping has the public recommendation request fields."""

    entry_type = _entry_type(payload)
    match entry_type:
        case "modify" | "clarify" | "confirm":
            return True
        case "create":
            return _has_create_request_fields(payload)
        case _:
            return _has_create_request_fields(payload)


def _graph_payload_from_mapping(
    payload: Mapping[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any] | None:
    if _looks_like_recommendation_request(payload):
        return _state_from_recommendation_request(payload, request_id=request_id)
    return None


def _state_from_recommendation_request(
    request: Mapping[str, Any],
    *,
    request_id: str | None,
) -> dict[str, Any]:
    resolved_request_id = request_id or _text_or_none(request.get("requestId")) or "agentcore-v2"
    if _entry_type(request) in {"modify", "clarify", "confirm"}:
        return {
            "request": _followup_request(request, request_id=resolved_request_id),
            "profile": {},
        }
    normalized_request = _request_from_recommendation_request(
        request,
        request_id=resolved_request_id,
    )
    return {
        "request": normalized_request,
        "profile": {},
    }


def _request_from_recommendation_request(
    request: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    themes = _normalize_theme_values(
        request.get("activeRequiredThemes", request.get("themes", ())),
    )
    return {
        "request_id": request_id,
        "country": request["country"],
        "travel_month": request["travelMonth"],
        "travel_year": request.get("travelYear"),
        "trip_type": request["tripType"],
        "destination_id": request.get("destinationId"),
        "include_festivals": request["includeFestivals"],
        "themes": themes,
        "raw_query": request.get("rawQuery", request.get("naturalLanguageQuery", "")),
        "user_location": request.get("userLocation"),
    }


def _followup_request(
    request: Mapping[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    normalized = dict(request)
    normalized["request_id"] = request_id
    thread_id = _text_or_none(
        request.get("threadId", request.get("thread_id", request.get("sessionId"))),
    )
    if thread_id is not None:
        normalized.setdefault("thread_id", thread_id)
    return normalized


def _has_create_request_fields(payload: Mapping[str, Any]) -> bool:
    has_required_fields = all(
        key in payload
        for key in ("entryType", "country", "travelMonth", "tripType", "includeFestivals")
    )
    return has_required_fields and _has_theme_selection(payload)


def _has_theme_selection(payload: Mapping[str, Any]) -> bool:
    value = payload.get("activeRequiredThemes", payload.get("themes"))
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, (list, tuple)):
        return False
    return any(isinstance(item, str) and item.strip() for item in value)


def _normalize_theme_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_theme_label(value),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_theme_label(item) for item in value if isinstance(item, str) and item.strip())


def _theme_label(value: str) -> str:
    normalized = value.strip()
    return THEME_ID_TO_LABEL.get(normalized, normalized)


def _emit_entrypoint_route(entry: Mapping[str, Any]) -> None:
    _LOGGER.warning(json.dumps(dict(entry), ensure_ascii=False, separators=(",", ":")))


def _entry_type(payload: Mapping[str, Any]) -> str:
    value = payload.get("entryType", payload.get("entry_type", "create"))
    if not isinstance(value, str):
        return "create"
    return value.strip().lower().replace("-", "_")


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


# Aliases
handler = handle_v2_invocation
invoke = handle_v2_invocation


__all__ = [
    "extract_graph_payload",
    "extract_recommendation_payload",
    "extract_request_id",
    "extract_actor_id",
    "handle_v2_invocation",
    "handler",
    "invoke",
]

