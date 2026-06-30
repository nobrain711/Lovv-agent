from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import time
from typing import Final, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.common.telemetry_metrics import (
    JsonValue,
    LlmMetricPayload,
    LlmUsageMetric,
    aggregate_llm_metrics,
    context_window_for_model,
    llm_usage_count,
    metrics_since,
    record_llm_usage,
    reset_llm_usage,
    restore_llm_usage,
)
from lovv_agent_v2.common.telemetry_safety import sanitize_text
from lovv_agent_v2.common.telemetry_state import bool_value, mapping_value, nested_mapping, nested_text, request_mapping, text_value, themes

type LogEntry = dict[str, JsonValue]
type GraphEnvelope = Mapping[str, UnifiedAgentState | str | None]

NodeInputT = TypeVar("NodeInputT")
NodeResultT = TypeVar("NodeResultT")

LOG_TYPE_AGENT_NODE_METRIC: Final = "AGENT_NODE_METRIC"
DEFAULT_SERVICE_NAME: Final = "LovvAgentV2"
MAX_ERROR_MESSAGE_CHARS: Final = 300

_TRACER = trace.get_tracer("lovv_agent_v2.common.telemetry")
_TELEMETRY_INITIALIZED = False


def init_telemetry(service_name: str = DEFAULT_SERVICE_NAME) -> None:
    global _TELEMETRY_INITIALIZED
    if _TELEMETRY_INITIALIZED:
        return

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return

    resource = Resource.create({"service.name": service_name})
    provider = _build_tracer_provider(TracerProvider, resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ImportError:
        pass
    else:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)
    _configure_xray_propagator()
    _TELEMETRY_INITIALIZED = True


def trace_invocation(
    state: UnifiedAgentState,
    operation: Callable[[], NodeResultT],
) -> NodeResultT:
    token = reset_llm_usage()
    request_id = _request_id(state)
    with _TRACER.start_as_current_span("LovvAgentInvocation") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("agent.run_id", nested_text(state, "trace", "agent_run_id", default="unknown"))
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - top span records and re-raises.
            _record_span_error(span, exc)
            raise
        finally:
            restore_llm_usage(token)


def trace_node(
    node_name: str,
    node_func: Callable[[UnifiedAgentState], NodeResultT],
) -> Callable[[UnifiedAgentState], NodeResultT]:
    return _trace_with_state(node_name, node_func, lambda state: state)


def trace_graph_envelope_node(
    node_name: str,
    node_func: Callable[[GraphEnvelope], GraphEnvelope],
) -> Callable[[GraphEnvelope], GraphEnvelope]:
    return _trace_with_state(node_name, node_func, _state_from_envelope)


def _trace_with_state(
    node_name: str,
    node_func: Callable[[NodeInputT], NodeResultT],
    state_resolver: Callable[[NodeInputT], UnifiedAgentState],
) -> Callable[[NodeInputT], NodeResultT]:
    def wrapper(node_input: NodeInputT) -> NodeResultT:
        state = state_resolver(node_input)
        request_id = _request_id(state)
        metric_start = llm_usage_count()
        started_at = time.perf_counter()
        with _TRACER.start_as_current_span(f"node.{node_name}") as span:
            _set_node_span_attributes(span, node_name, state, request_id)
            try:
                result = node_func(node_input)
            except Exception as exc:  # noqa: BLE001 - node span records and re-raises.
                duration_ms = _duration_ms(started_at)
                _record_span_error(span, exc)
                _emit_node_metric(
                    _node_log_entry(
                        state=state,
                        node_name=node_name,
                        request_id=request_id,
                        duration_ms=duration_ms,
                        status="error",
                        result=None,
                        error_message=sanitize_text(str(exc) or type(exc).__name__),
                        llm_metrics=metrics_since(metric_start),
                    ),
                )
                raise
            duration_ms = _duration_ms(started_at)
            span.set_attribute("node.duration_ms", duration_ms)
            span.set_attribute("node.status", "success")
            _emit_node_metric(
                _node_log_entry(
                    state=state,
                    node_name=node_name,
                    request_id=request_id,
                    duration_ms=duration_ms,
                    status="success",
                    result=result,
                    error_message=None,
                    llm_metrics=metrics_since(metric_start),
                ),
            )
            return result

    return wrapper


def _build_tracer_provider(provider_type, resource):
    try:
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    except ImportError:
        return provider_type(resource=resource)
    return provider_type(resource=resource, id_generator=AwsXRayIdGenerator())


def _configure_xray_propagator() -> None:
    try:
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.sdk.extension.aws.propagator.awsxray import AwsXRayPropagator
    except ImportError:
        return
    set_global_textmap(AwsXRayPropagator())


def _state_from_envelope(envelope: GraphEnvelope) -> UnifiedAgentState:
    state = envelope.get("state")
    if not isinstance(state, Mapping):
        raise TypeError("LangGraph envelope.state must be UnifiedAgentState")
    return state


def _set_node_span_attributes(
    span,
    node_name: str,
    state: UnifiedAgentState,
    request_id: str,
) -> None:
    span.set_attribute("node.name", node_name)
    span.set_attribute("node.request_id", request_id)
    request = request_mapping(state)
    request_themes = themes(request)
    span.set_attribute("request.theme_count", len(request_themes))
    span.set_attribute("request.include_festivals", bool_value(request.get("include_festivals", request.get("includeFestivals"))))
    span.set_attribute("request.trip_type", text_value(request.get("trip_type", request.get("tripType"))))
    span.set_attribute(
        "request.natural_language_query_length",
        len(text_value(request.get("natural_language_query", request.get("naturalLanguageQuery")))),
    )


def _node_log_entry(
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


def _emit_node_metric(entry: LogEntry) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _input_summary(state: UnifiedAgentState) -> dict[str, JsonValue]:
    request = request_mapping(state)
    request_themes = themes(request)
    return {
        "themes": list(request_themes),
        "themeCount": len(request_themes),
        "tripType": text_value(request.get("trip_type", request.get("tripType"))),
        "includeFestivals": bool_value(request.get("include_festivals", request.get("includeFestivals"))),
        "queryLength": len(text_value(request.get("natural_language_query", request.get("naturalLanguageQuery")))),
    }


def _output_summary(state: UnifiedAgentState, result: NodeResultT | None) -> dict[str, JsonValue]:
    summary: dict[str, JsonValue] = {}
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
        summary["itineraryItemCount"] = len(itinerary) if isinstance(itinerary, (list, tuple)) else 0
    response = mapping_value(state.get("response"))
    if response:
        summary["responseStatus"] = text_value(response.get("response_status"))
    return summary


def _request_id(state: UnifiedAgentState) -> str:
    trace_payload = mapping_value(state.get("trace"))
    request_payload = request_mapping(state)
    return (
        text_value(trace_payload.get("recommendation_request_id")) if trace_payload else ""
    ) or text_value(request_payload.get("request_id", request_payload.get("requestId"))) or "unknown"


def _record_span_error(span, exc: Exception) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)))


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "LOG_TYPE_AGENT_NODE_METRIC",
    "LlmUsageMetric",
    "context_window_for_model",
    "init_telemetry",
    "record_llm_usage",
    "sanitize_text",
    "trace_graph_envelope_node",
    "trace_invocation",
    "trace_node",
]
