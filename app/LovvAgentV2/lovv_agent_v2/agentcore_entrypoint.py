"""AgentCore Runtime HTTP entrypoint for V2."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

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


def handle_v2_invocation(event: Any, context: Any | None = None) -> dict[str, Any]:
    """Invoke the V2 recommendation graph from an AgentCore payload."""

    payload = extract_recommendation_payload(event)
    session_id = extract_request_id(event)
    actor_id = extract_actor_id(event) or session_id

    # Requirement 2: thread_id and actor_id plumbing
    graph_config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": actor_id,
        }
    }
    return _cached_live_harness().invoke(
        payload,
        request_id=session_id,
        graph_config=graph_config,
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


def _decode_json_if_needed(value: Any) -> Any:
    """Decode JSON strings or bytes while leaving structured values intact."""

    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("AgentCore invocation payload is empty")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "AgentCore invocation string must be JSON",
            ) from exc
    return value


def _looks_like_recommendation_request(payload: Mapping[str, Any]) -> bool:
    """Return whether a mapping has the public recommendation request fields."""

    return _REQUEST_FIELD_MARKERS.issubset(payload.keys())


# Aliases
handler = handle_v2_invocation
invoke = handle_v2_invocation


__all__ = [
    "extract_recommendation_payload",
    "extract_request_id",
    "extract_actor_id",
    "handle_v2_invocation",
    "handler",
    "invoke",
]

