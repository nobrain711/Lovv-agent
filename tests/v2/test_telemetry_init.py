from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest

from lovv_agent_v2.common import telemetry
from lovv_agent_v2.common.telemetry_callback_compat import (
    patch_langchain_callback_resume_compat,
)


class FakeResource:
    def __init__(self, attributes: dict[str, str]) -> None:
        self.attributes = attributes

    @classmethod
    def create(cls, attributes: dict[str, str]) -> FakeResource:
        return cls(attributes)


class FakeSpanProcessor:
    def __init__(self, exporter: FakeExporter) -> None:
        self.exporter = exporter


class FakeExporter:
    pass


class FakeTracerProvider:
    def __init__(
        self,
        resource: FakeResource | None = None,
        sampler: object | None = None,
    ) -> None:
        self.resource = resource
        self.sampler = sampler
        self.processors: list[FakeSpanProcessor] = []

    def add_span_processor(self, processor: FakeSpanProcessor) -> None:
        self.processors.append(processor)

    def get_tracer(self, *args: object, **kwargs: object) -> str:
        return "fake-tracer"


class ExistingTracerProvider:
    def __init__(self) -> None:
        self.processors: list[FakeSpanProcessor] = []

    def add_span_processor(self, processor: FakeSpanProcessor) -> None:
        self.processors.append(processor)

    def get_tracer(self, *args: object, **kwargs: object) -> str:
        return "existing-tracer"


class ProxyTracerProvider:
    def get_tracer(self, *args: object, **kwargs: object) -> str:
        return "proxy-tracer"


def test_init_telemetry_reuses_existing_sdk_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: AgentCore or auto-instrumentation already installed an SDK provider.
    _install_fake_otel_modules(monkeypatch)
    existing_provider = FakeTracerProvider()
    set_calls: list[FakeTracerProvider] = []
    monkeypatch.setattr(telemetry.trace, "get_tracer_provider", lambda: existing_provider)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", set_calls.append)
    monkeypatch.setattr(telemetry, "_TELEMETRY_INITIALIZED", False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

    # When: V2 telemetry initializes inside the runtime.
    telemetry.init_telemetry()

    # Then: V2 keeps the existing provider so AgentCore ADOT export stays intact.
    assert set_calls == []
    assert existing_provider.processors == []
    init_log = json.loads(capsys.readouterr().out)
    assert init_log["logType"] == "AGENT_TELEMETRY_INIT"
    assert init_log["sdkAvailable"] is True
    assert init_log["exporterAvailable"] is True
    assert init_log["setProviderActive"] is False
    assert init_log["adotProviderReused"] is True
    assert init_log["providerProcessorAttached"] is False
    assert init_log["existingProviderProcessorAttached"] is False
    assert init_log["samplerName"] == "adot-managed"


def test_init_telemetry_skips_provider_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_otel_modules(monkeypatch)
    set_calls: list[FakeTracerProvider] = []
    monkeypatch.setattr(telemetry.trace, "get_tracer_provider", lambda: ProxyTracerProvider())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", set_calls.append)
    monkeypatch.setattr(telemetry, "_TELEMETRY_INITIALIZED", False)
    monkeypatch.setenv("AGENT_OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

    telemetry.init_telemetry()

    assert set_calls == []
    init_log = json.loads(capsys.readouterr().out)
    assert init_log["telemetryEnabled"] is False
    assert init_log["providerProcessorAttached"] is False


def test_init_telemetry_sets_provider_when_no_sdk_provider_exists(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: only the default proxy provider exists.
    _install_fake_otel_modules(monkeypatch)
    set_calls: list[FakeTracerProvider] = []
    monkeypatch.setattr(telemetry.trace, "get_tracer_provider", lambda: ProxyTracerProvider())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", set_calls.append)
    monkeypatch.setattr(telemetry, "_TELEMETRY_INITIALIZED", False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

    # When: V2 telemetry initializes without an existing SDK provider.
    telemetry.init_telemetry()

    # Then: V2 installs a provider that has the OTLP exporter.
    assert len(set_calls) == 1
    assert set_calls[0].sampler == "ALWAYS_ON"
    assert len(set_calls[0].processors) == 1
    assert isinstance(set_calls[0].processors[0].exporter, FakeExporter)
    init_log = json.loads(capsys.readouterr().out)
    assert init_log["logType"] == "AGENT_TELEMETRY_INIT"
    assert init_log["otelExporterOtlpEndpointPresent"] is True
    assert init_log["samplerName"] == "ALWAYS_ON"


def test_callback_compat_patches_resume_and_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: the installed callback base lacks LangGraph resume/interrupt hooks.
    callback_base = ModuleType("langchain_core.callbacks.base")
    base_handler = type("BaseCallbackHandler", (), {})
    callback_base.BaseCallbackHandler = base_handler
    monkeypatch.setitem(sys.modules, "langchain_core.callbacks.base", callback_base)

    # When: telemetry compatibility patch runs.
    patch_langchain_callback_resume_compat()

    # Then: both hooks exist for AgentCore interrupt/resume callback dispatch.
    assert hasattr(base_handler, "on_resume")
    assert hasattr(base_handler, "on_interrupt")


def _install_fake_otel_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    resources = ModuleType("opentelemetry.sdk.resources")
    resources.Resource = FakeResource

    sdk_trace = ModuleType("opentelemetry.sdk.trace")
    sdk_trace.TracerProvider = FakeTracerProvider

    trace_export = ModuleType("opentelemetry.sdk.trace.export")
    trace_export.BatchSpanProcessor = FakeSpanProcessor

    trace_sampling = ModuleType("opentelemetry.sdk.trace.sampling")
    trace_sampling.ALWAYS_ON = "ALWAYS_ON"

    otlp_exporter = ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    otlp_exporter.OTLPSpanExporter = FakeExporter

    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", resources)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", sdk_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", trace_export)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.sampling", trace_sampling)
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        otlp_exporter,
    )
