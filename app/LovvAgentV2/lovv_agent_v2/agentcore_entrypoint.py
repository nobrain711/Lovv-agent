"""AgentCore Runtime HTTP entrypoint for V2."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from lovv_agent_v2.agentcore_io import decode_json_if_needed as _decode_json_if_needed
from lovv_agent_v2.agentcore_io import extract_resume_value, extract_thread_id, interrupt_response
from lovv_agent_v2.agents.profile.evidence import (
    InMemoryProfileEvidenceCache,
    ProfileEvidenceResolver,
)
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
    resume_value = extract_resume_value(event)
    clarify_resume = _clarify_resume_value(event) if resume_value is None else None
    payload = (
        Command(resume=resume_value if resume_value is not None else clarify_resume)
        if resume_value is not None or clarify_resume is not None
        else extract_graph_payload(event, request_id=request_id)
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
            "actor_id": actor_id,
        }
    }
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
    if not isinstance(decoded, Mapping) or _entry_type(decoded) != "clarify":
        return None
    return extract_recommendation_payload(decoded)


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


def extract_request_id(event: Any) -> str | None:
    """Read an optional request id from common AgentCore/HTTP wrappers."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    for key in ("requestId", "request_id", "invocationId", "sessionId"):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    headers = decoded.get("headers")
    if isinstance(headers, Mapping):
        for key in ("x-request-id", "X-Request-Id", "x-amzn-trace-id"):
            value = headers.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_actor_id(event: Any) -> str | None:
    """Extract an optional pseudonymized actor_id from event."""

    decoded = _decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return None
    for key in ("actorId", "actor_id", "userId"):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
    return {
        "request_id": request_id,
        "country": request["country"],
        "travel_month": request["travelMonth"],
        "travel_year": request.get("travelYear"),
        "trip_type": request["tripType"],
        "destination_id": request.get("destinationId"),
        "include_festivals": request["includeFestivals"],
        "themes": tuple(request.get("activeRequiredThemes", request.get("themes", ()))),
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

