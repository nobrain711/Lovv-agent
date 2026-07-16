from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from typing import Final

type TelemetryInitValue = str | bool

LOG_TYPE_AGENT_TELEMETRY_INIT: Final = "AGENT_TELEMETRY_INIT"


def add_span_processor(provider, processor_type, exporter_type) -> bool:
    add_span_processor_fn = getattr(provider, "add_span_processor", None)
    if not callable(add_span_processor_fn):
        return False
    add_span_processor_fn(processor_type(exporter_type()))
    return True


def build_tracer_provider(provider_type, resource, sampler):
    try:
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    except ImportError:
        return provider_type(resource=resource, sampler=sampler)
    return provider_type(
        resource=resource,
        id_generator=AwsXRayIdGenerator(),
        sampler=sampler,
    )


def telemetry_init_base(service_name: str) -> dict[str, TelemetryInitValue]:
    return {
        "timestamp": _timestamp(),
        "level": "INFO",
        "logType": LOG_TYPE_AGENT_TELEMETRY_INIT,
        "serviceName": service_name,
        "otelServiceName": os.getenv("OTEL_SERVICE_NAME", ""),
        "otelTracesExporter": os.getenv("OTEL_TRACES_EXPORTER", ""),
        "otelExporterOtlpProtocol": os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", ""),
        "otelExporterOtlpEndpointPresent": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
    }


def emit_telemetry_init(entry: dict[str, TelemetryInitValue]) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "add_span_processor",
    "build_tracer_provider",
    "emit_telemetry_init",
    "telemetry_init_base",
]
