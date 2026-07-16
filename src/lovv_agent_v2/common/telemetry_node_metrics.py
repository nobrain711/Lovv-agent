from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Final, TypeVar

from lovv_agent_v2.common.telemetry_metrics import (
    JsonValue,
    LlmUsageMetric,
    aggregate_llm_metrics,
)
from lovv_agent_v2.common.telemetry_state import (
    bool_value,
    mapping_value,
    nested_mapping,
    text_value,
    themes,
)
from lovv_agent_v2.core.state import UnifiedAgentState

type LogEntry = dict[str, JsonValue]

NodeResultT = TypeVar("NodeResultT")

LOG_TYPE_AGENT_NODE_METRIC: Final = "AGENT_NODE_METRIC"
MAX_ERROR_MESSAGE_CHARS: Final = 300


def node_log_entry(
    *,
    state: UnifiedAgentState,
    node_name: str,
    request_id: str,
    duration_ms: int,
    status: str,
    result: NodeResultT | None,
    error_message: str | None,
    llm_metrics: tuple[LlmUsageMetric, ...],
) -> LogEntry:
    entry: LogEntry = {
        "timestamp": _timestamp(),
        "level": "ERROR" if status == "error" else "INFO",
        "requestId": request_id,
        "logType": LOG_TYPE_AGENT_NODE_METRIC,
        "nodeName": node_name,
        "durationMs": duration_ms,
        "status": status,
        "inputSummary": _input_summary(state),
        "outputSummary": _output_summary(state, result),
    }
    metrics = aggregate_llm_metrics(llm_metrics)
    if metrics is not None:
        entry["llmMetrics"] = metrics
    if error_message is not None:
        entry["errorMessage"] = error_message[:MAX_ERROR_MESSAGE_CHARS]
    return entry


def emit_node_metric(entry: LogEntry) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _input_summary(state: UnifiedAgentState) -> dict[str, JsonValue]:
    request = mapping_value(state.get("request")) or {}
    city_input = nested_mapping(state, "intent", "city_select_input") or {}
    request_themes = themes(request)
    active_themes = themes(city_input)
    summary_source = request or city_input
    return {
        "themes": list(request_themes),
        "themeCount": len(request_themes),
        "requestThemes": list(request_themes),
        "activeRequiredThemes": list(active_themes),
        "activeThemeCount": len(active_themes),
        "tripType": text_value(summary_source.get("trip_type", summary_source.get("tripType"))),
        "includeFestivals": bool_value(
            summary_source.get("include_festivals", summary_source.get("includeFestivals")),
        ),
        "queryLength": len(
            text_value(
                summary_source.get("natural_language_query", summary_source.get("naturalLanguageQuery")),
            ),
        ),
    }


def _output_summary(state: UnifiedAgentState, result: NodeResultT | None) -> dict[str, JsonValue]:
    summary: dict[str, JsonValue] = {}
    summary.update(_routing_summary(state, result))
    summary.update(_route_loop_summary(state))
    selected_city = getattr(result, "selected_city", None)
    city_select_result = nested_mapping(state, "city_select", "city_selection_result")
    if selected_city is None and city_select_result:
        selected_city = city_select_result.get("selected_city")
    if isinstance(selected_city, Mapping):
        summary["selectedCity"] = text_value(selected_city.get("city_id"))
    elif selected_city is not None:
        summary["selectedCity"] = getattr(selected_city, "city_id", None)

    recommended_places = getattr(result, "recommended_places", None)
    if isinstance(recommended_places, (list, tuple)):
        summary["candidateCount"] = len(recommended_places)

    planner_output = nested_mapping(state, "planner", "planner_output")
    if planner_output:
        itinerary = planner_output.get("itinerary", ())
        summary["itineraryItemCount"] = (
            len(itinerary) if isinstance(itinerary, (list, tuple)) else 0
        )
    response = mapping_value(state.get("response"))
    if response:
        summary["responseStatus"] = text_value(response.get("response_status"))
    return summary


def _routing_summary(
    state: UnifiedAgentState,
    result: NodeResultT | None,
) -> dict[str, JsonValue]:
    routing = _routing_mapping(result) or mapping_value(state.get("routing"))
    if routing is None:
        return {}
    completed_groups = routing.get("completed_groups", ())
    return {
        "routeNextNode": text_value(routing.get("next_node")),
        "routeNeedsClarification": bool_value(routing.get("needs_clarification")),
        "routeClarificationReasonCode": text_value(
            routing.get("clarification_reason_code"),
        ),
        "routeCompletedGroupCount": (
            len(completed_groups) if isinstance(completed_groups, (list, tuple)) else 0
        ),
    }


def _routing_mapping(result: NodeResultT | None) -> Mapping[str, object] | None:
    if not isinstance(result, Mapping):
        return None
    return mapping_value(result.get("routing"))


def _route_loop_summary(state: UnifiedAgentState) -> dict[str, JsonValue]:
    trace = mapping_value(state.get("trace"))
    if trace is None:
        return {}
    guard = mapping_value(trace.get("route_loop_guard"))
    if guard is None:
        return {}
    return {
        "routeLoopReason": text_value(guard.get("reason")),
        "routeRepeatedPair": text_value(guard.get("repeated_pair")),
        "routeRepeatedPairCount": _int_value(guard.get("repeated_pair_count")),
    }


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = ["LOG_TYPE_AGENT_NODE_METRIC", "emit_node_metric", "node_log_entry"]
