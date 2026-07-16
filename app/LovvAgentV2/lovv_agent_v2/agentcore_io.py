from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_WRAPPER_KEYS = ("payload", "input", "request", "body", "prompt")


def decode_json_if_needed(value: Any) -> Any:
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


def _candidate_mappings(event: Any) -> tuple[Mapping[str, Any], ...]:
    decoded = decode_json_if_needed(event)
    if not isinstance(decoded, Mapping):
        return ()
    candidates = [decoded]
    for key in _WRAPPER_KEYS:
        if key not in decoded:
            continue
        nested = decode_json_if_needed(decoded[key])
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return tuple(candidates)


def extract_resume_value(event: Any) -> Any | None:
    for payload in _candidate_mappings(event):
        if "resume" in payload:
            return payload["resume"]
        if "resumeValue" in payload:
            return payload["resumeValue"]
    return None


def extract_thread_id(event: Any, fallback: str | None = None) -> str | None:
    for payload in _candidate_mappings(event):
        session_id = payload.get("sessionId")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
    return fallback


def extract_request_id(event: Any) -> str | None:
    for payload in _candidate_mappings(event):
        for key in ("requestId", "request_id", "invocationId", "sessionId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        headers = payload.get("headers")
        if isinstance(headers, Mapping):
            for key in ("x-request-id", "X-Request-Id", "x-amzn-trace-id"):
                value = headers.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def extract_actor_id(event: Any) -> str | None:
    for payload in _candidate_mappings(event):
        for key in ("actorId", "actor_id", "userId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def interrupt_response(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, Mapping):
        return None
    interrupts = result.get("__interrupt__")
    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None
    first_interrupt = interrupts[0]
    value = getattr(first_interrupt, "value", None)
    return dict(value) if isinstance(value, Mapping) else None
