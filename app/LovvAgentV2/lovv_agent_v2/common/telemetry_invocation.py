from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from typing import TypeVar

from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.common.telemetry_invocation_metrics import (
    emit_invocation_metric,
    invocation_log_entry,
)
from lovv_agent_v2.common.telemetry_memory import MemoryEventInspector
from lovv_agent_v2.common.telemetry_metrics import (
    aggregate_duration_metrics,
    aggregate_tool_metrics,
    metrics_since,
    reset_llm_usage,
    reset_step_durations,
    reset_tool_calls,
    restore_llm_usage,
    restore_step_durations,
    restore_tool_calls,
    step_durations_since,
    tool_calls_since,
)
from lovv_agent_v2.common.telemetry_safety import (
    sanitize_text,
    sanitized_exception_attributes,
)
from lovv_agent_v2.common.telemetry_state import (
    mapping_value,
    nested_text,
    request_mapping,
    text_value,
)
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.core.state import UnifiedAgentState

NodeResultT = TypeVar("NodeResultT")

_TRACER = trace.get_tracer("lovv_agent_v2.common.telemetry")


def trace_invocation(
    state: UnifiedAgentState,
    operation: Callable[[], NodeResultT],
) -> NodeResultT:
    llm_token = reset_llm_usage()
    step_token = reset_step_durations()
    tool_token = reset_tool_calls()
    request_id = _request_id(state)
    started_at = time.perf_counter()
    with _TRACER.start_as_current_span(
        "LovvAgentInvocation",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("gen_ai.agent.name", "LovvAgentV2")
        span.set_attribute("gen_ai.system", "lovv")
        span.set_attribute("request.id", request_id)
        span.set_attribute(
            "agent.run_id",
            nested_text(state, "trace", "agent_run_id", default="unknown"),
        )
        span.set_attribute(
            "thread.id",
            nested_text(state, "trace", "thread_id", default="unknown"),
        )
        span.set_attribute(
            "actor.id",
            nested_text(state, "trace", "actor_id", default="unknown"),
        )
        try:
            result = operation()
        except GraphInterrupt:
            _emit_invocation(state, request_id, started_at, "interrupt", None, None)
            raise
        except Exception as exc:  # noqa: BLE001 - top span records and re-raises.
            _record_span_error(span, exc)
            _emit_invocation(
                state,
                request_id,
                started_at,
                "error",
                None,
                sanitize_text(str(exc) or type(exc).__name__),
            )
            raise
        else:
            span.set_attribute("invocation.duration_ms", _duration_ms(started_at))
            span.set_attribute("invocation.status", "success")
            _emit_invocation(state, request_id, started_at, "success", result, None)
            return result
        finally:
            restore_llm_usage(llm_token)
            restore_step_durations(step_token)
            restore_tool_calls(tool_token)
            _force_flush_traces()


def _emit_invocation(
    state: UnifiedAgentState,
    request_id: str,
    started_at: float,
    status: str,
    result: NodeResultT | None,
    error_message: str | None,
) -> None:
    _emit_memory_event_guard(state)
    emit_invocation_metric(
        invocation_log_entry(
            state=state,
            request_id=request_id,
            duration_ms=_duration_ms(started_at),
            status=status,
            result=result,
            error_message=error_message,
            llm_metrics=metrics_since(0),
            step_metrics=aggregate_duration_metrics(step_durations_since(0)),
            tool_metrics=aggregate_tool_metrics(tool_calls_since(0)),
        ),
    )


def _emit_memory_event_guard(state: UnifiedAgentState) -> None:
    inspector = runtime_value(state, "memory_event_inspector")
    if isinstance(inspector, MemoryEventInspector):
        inspector.emit_for_state(state)


def _request_id(state: UnifiedAgentState) -> str:
    trace_payload = mapping_value(state.get("trace"))
    request_payload = request_mapping(state)
    return (
        text_value(trace_payload.get("recommendation_request_id"))
        if trace_payload
        else ""
    ) or text_value(
        request_payload.get("request_id", request_payload.get("requestId")),
    ) or "unknown"


def _record_span_error(span, exc: Exception) -> None:
    span.add_event("exception", attributes=sanitized_exception_attributes(exc))
    span.set_status(
        Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
    )


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _force_flush_traces() -> None:
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return
    try:
        force_flush(timeout_millis=2000)
    except Exception:  # noqa: BLE001 - telemetry flush must not change graph outcome.
        return


__all__ = ["trace_invocation"]
