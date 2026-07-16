from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
import uuid


@dataclass(frozen=True, slots=True)
class TraceContext:
    request_id: str | None = None
    thread_id: str | None = None
    actor_id: str | None = None


def with_trace_context(payload: dict[str, Any], context: TraceContext) -> dict[str, Any]:
    graph_payload = dict(payload)
    trace_value = graph_payload.get("trace")
    trace = dict(trace_value) if isinstance(trace_value, Mapping) else {}
    request = graph_payload.get("request")
    request_payload = request if isinstance(request, Mapping) else {}
    trace.setdefault(
        "recommendation_request_id",
        context.request_id
        or _text_or_none(trace.get("recommendation_request_id"))
        or _text_or_none(request_payload.get("request_id"))
        or _text_or_none(request_payload.get("requestId"))
        or "agentcore-v2",
    )
    trace.setdefault("thread_id", context.thread_id or "")
    trace.setdefault("actor_id", context.actor_id or "")
    trace.setdefault("agent_run_id", f"run-{uuid.uuid4()}")
    graph_payload["trace"] = trace
    return graph_payload


def trace_context_from_graph_config(
    payload: dict[str, Any],
    *,
    request_id: str | None,
    graph_config: Mapping[str, Any],
) -> TraceContext:
    trace_value = payload.get("trace")
    trace = trace_value if isinstance(trace_value, Mapping) else {}
    request = payload.get("request")
    request_payload = request if isinstance(request, Mapping) else {}
    configurable = graph_config.get("configurable")
    config_payload = configurable if isinstance(configurable, Mapping) else {}
    return TraceContext(
        request_id=(
            request_id
            or _text_or_none(trace.get("recommendation_request_id"))
            or _text_or_none(request_payload.get("request_id"))
            or _text_or_none(request_payload.get("requestId"))
        ),
        thread_id=_text_or_none(config_payload.get("thread_id")),
        actor_id=_text_or_none(config_payload.get("actor_id")),
    )


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["TraceContext", "trace_context_from_graph_config", "with_trace_context"]
