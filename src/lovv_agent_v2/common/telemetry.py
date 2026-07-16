from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Final, TypeVar

from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.common.telemetry_callback_compat import (
    patch_langchain_callback_resume_compat,
)
from lovv_agent_v2.common.telemetry_init_log import add_span_processor, build_tracer_provider, emit_telemetry_init, telemetry_init_base
from lovv_agent_v2.common.telemetry_metrics import (
    LlmUsageMetric,
    context_window_for_model,
    llm_usage_count,
    metrics_since,
    record_llm_usage,
    record_step_duration,
)
from lovv_agent_v2.common.telemetry_invocation import trace_invocation
from lovv_agent_v2.common.telemetry_node_metrics import (
    LOG_TYPE_AGENT_NODE_METRIC,
    emit_node_metric,
    node_log_entry,
)
from lovv_agent_v2.common.telemetry_route_guard import record_route_visit
from lovv_agent_v2.common.telemetry_safety import (
    sanitize_text,
    sanitized_exception_attributes,
)
from lovv_agent_v2.common.telemetry_state import (
    bool_value,
    mapping_value,
    request_mapping,
    text_value,
    themes,
)

type GraphEnvelope = Mapping[str, UnifiedAgentState | str | None]

NodeInputT = TypeVar("NodeInputT")
NodeResultT = TypeVar("NodeResultT")

DEFAULT_SERVICE_NAME: Final = "LovvAgentV2"

_TRACER = trace.get_tracer("lovv_agent_v2.common.telemetry")
_TELEMETRY_INITIALIZED = False


def init_telemetry(service_name: str = DEFAULT_SERVICE_NAME) -> None:
    global _TELEMETRY_INITIALIZED, _TRACER
    patch_langchain_callback_resume_compat()
    if _TELEMETRY_INITIALIZED:
        return
    if not _telemetry_enabled():
        emit_telemetry_init(
            {
                "telemetryEnabled": False,
                "sdkAvailable": False,
                "exporterAvailable": False,
                "providerProcessorAttached": False,
                "existingProviderProcessorAttached": False,
                **telemetry_init_base(service_name),
            },
        )
        _TELEMETRY_INITIALIZED = True
        return

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    except ImportError as exc:
        emit_telemetry_init(
            {
                "sdkAvailable": False,
                "exporterAvailable": False,
                "missingModule": exc.name or type(exc).__name__,
                **telemetry_init_base(service_name),
            },
        )
        return

    resource = Resource.create({"service.name": service_name})
    exporter_type = None
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ImportError:
        pass
    else:
        exporter_type = OTLPSpanExporter

    # Check whether ADOT or another framework already installed an SDK provider.
    # If so, DO NOT replace it — replacing the provider breaks the AgentCore
    # observability pipeline that ADOT configures.  Instead, just attach our
    # own exporter processor to the existing provider so our spans also flow.
    current_provider = trace.get_tracer_provider()
    adot_provider_active = isinstance(current_provider, TracerProvider)

    provider_processor_attached = existing_provider_processor_attached = False

    if not adot_provider_active:
        # No SDK provider — we're running locally or without auto-instrumentation.
        # Create and install our own provider.
        provider = build_tracer_provider(TracerProvider, resource, ALWAYS_ON)
        if exporter_type is not None:
            provider_processor_attached = add_span_processor(
                provider,
                BatchSpanProcessor,
                exporter_type,
            )
        trace.set_tracer_provider(provider)
        current_provider = trace.get_tracer_provider()

    _TRACER = trace.get_tracer("lovv_agent_v2.common.telemetry")
    _configure_xray_propagator()
    emit_telemetry_init(
        {
            "telemetryEnabled": True,
            "sdkAvailable": True,
            "exporterAvailable": exporter_type is not None,
            "providerType": type(current_provider).__name__,
            "activeProviderType": type(current_provider).__name__,
            "setProviderActive": not adot_provider_active,
            "adotProviderReused": adot_provider_active,
            "providerProcessorAttached": provider_processor_attached,
            "existingProviderProcessorAttached": existing_provider_processor_attached,
            "samplerName": "ALWAYS_ON" if not adot_provider_active else "adot-managed",
            **telemetry_init_base(service_name),
        },
    )
    _TELEMETRY_INITIALIZED = True


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
        record_route_visit(state, node_name)
        request_id = _request_id(state)
        metric_start = llm_usage_count()
        started_at = time.perf_counter()
        with _TRACER.start_as_current_span(
            f"node.{node_name}", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("gen_ai.operation.name", f"node.{node_name}")
            span.set_attribute("gen_ai.system", "lovv")
            _set_node_span_attributes(span, node_name, state, request_id)
            try:
                result = node_func(node_input)
            except GraphInterrupt:
                duration_ms = _duration_ms(started_at)
                span.set_attribute("node.duration_ms", duration_ms)
                span.set_attribute("node.status", "interrupt")
                emit_node_metric(
                    node_log_entry(
                        state=state,
                        node_name=node_name,
                        request_id=request_id,
                        duration_ms=duration_ms,
                        status="interrupt",
                        result=None,
                        error_message=None,
                        llm_metrics=metrics_since(metric_start),
                    ),
                )
                raise
            except Exception as exc:  # noqa: BLE001 - node span records and re-raises.
                duration_ms = _duration_ms(started_at)
                _record_span_error(span, exc)
                emit_node_metric(
                    node_log_entry(
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
            record_step_duration(node_name, duration_ms)
            span.set_attribute("node.duration_ms", duration_ms)
            span.set_attribute("node.status", "success")
            emit_node_metric(
                node_log_entry(
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
    span.set_attribute(
        "request.include_festivals",
        bool_value(request.get("include_festivals", request.get("includeFestivals"))),
    )
    span.set_attribute(
        "request.trip_type",
        text_value(request.get("trip_type", request.get("tripType"))),
    )
    span.set_attribute(
        "request.natural_language_query_length",
        len(
            text_value(
                request.get("natural_language_query", request.get("naturalLanguageQuery")),
            ),
        ),
    )


def _request_id(state: UnifiedAgentState) -> str:
    trace_payload = mapping_value(state.get("trace"))
    request_payload = request_mapping(state)
    return (
        text_value(trace_payload.get("recommendation_request_id")) if trace_payload else ""
    ) or text_value(
        request_payload.get("request_id", request_payload.get("requestId")),
    ) or "unknown"


def _record_span_error(span, exc: Exception) -> None:
    span.add_event("exception", attributes=sanitized_exception_attributes(exc))
    span.set_status(
        Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
    )


def _telemetry_enabled() -> bool:
    value = os.getenv("AGENT_OBSERVABILITY_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


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
