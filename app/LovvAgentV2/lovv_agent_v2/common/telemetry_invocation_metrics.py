from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Final

from lovv_agent_v2.common.telemetry_metrics import (
    JsonValue,
    LlmUsageMetric,
    aggregate_llm_metrics,
)
from lovv_agent_v2.common.telemetry_state import mapping_value, text_value
from lovv_agent_v2.core.state import UnifiedAgentState

type InvocationLogEntry = dict[str, JsonValue]

LOG_TYPE_AGENT_INVOCATION_METRIC: Final = "AGENT_INVOCATION_METRIC"
MAX_ERROR_MESSAGE_CHARS: Final = 300


def invocation_log_entry(
    *,
    state: UnifiedAgentState,
    request_id: str,
    duration_ms: int,
    status: str,
    result: object | None,
    error_message: str | None,
    llm_metrics: tuple[LlmUsageMetric, ...],
    step_metrics: dict[str, JsonValue] | None = None,
    tool_metrics: dict[str, JsonValue] | None = None,
) -> InvocationLogEntry:
    entry: InvocationLogEntry = {
        "timestamp": _timestamp(),
        "level": "ERROR" if status == "error" else "INFO",
        "requestId": request_id,
        "logType": LOG_TYPE_AGENT_INVOCATION_METRIC,
        "durationMs": duration_ms,
        "status": status,
        "trace": _trace_summary(state),
        "outputSummary": _output_summary(result),
    }
    metrics = aggregate_llm_metrics(llm_metrics)
    if metrics is not None:
        entry["llmMetrics"] = metrics
    if step_metrics is not None:
        entry["stepMetrics"] = step_metrics
    if tool_metrics is not None:
        entry["toolMetrics"] = tool_metrics
    if error_message is not None:
        entry["errorMessage"] = error_message[:MAX_ERROR_MESSAGE_CHARS]
    return entry


def emit_invocation_metric(entry: InvocationLogEntry) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _trace_summary(state: UnifiedAgentState) -> dict[str, JsonValue]:
    trace = mapping_value(state.get("trace"))
    if trace is None:
        return {}
    return {
        "recommendationRequestId": text_value(trace.get("recommendation_request_id")),
        "threadId": text_value(trace.get("thread_id")),
        "actorId": text_value(trace.get("actor_id")),
        "agentRunId": text_value(trace.get("agent_run_id")),
    }


def _output_summary(result: object | None) -> dict[str, JsonValue]:
    if not isinstance(result, Mapping):
        return {}
    response = mapping_value(result.get("response"))
    if response is not None:
        return {"responseStatus": text_value(response.get("response_status"))}
    interrupts = result.get("__interrupt__")
    if isinstance(interrupts, (list, tuple)) and interrupts:
        return {"responseStatus": "END_WAIT_USER"}
    return {}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "LOG_TYPE_AGENT_INVOCATION_METRIC",
    "emit_invocation_metric",
    "invocation_log_entry",
]
