from __future__ import annotations

from collections.abc import Callable

from langgraph.errors import GraphInterrupt
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest

from lovv_agent_v2.common import telemetry
from lovv_agent_v2.common import telemetry_invocation


class FakeSpan:
    def __enter__(self) -> FakeSpan:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def set_attribute(self, *args: object) -> None:
        return None

    def record_exception(self, *args: object) -> None:
        return None

    def set_status(self, *args: object) -> None:
        return None


class ErrorRecordingSpan:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | bool]]] = []
        self.status = None

    def add_event(self, name: str, attributes: dict[str, str | bool]) -> None:
        self.events.append((name, attributes))

    def record_exception(self, *args: object) -> None:
        raise AssertionError("raw exceptions must not be recorded")

    def set_status(self, status: object) -> None:
        self.status = status


class FakeTracer:
    def start_as_current_span(self, _name: str, **_kwargs: bool) -> FakeSpan:
        return FakeSpan()


class RecordingTracer:
    def __init__(self) -> None:
        self.kwargs: dict[str, bool] = {}

    def start_as_current_span(self, _name: str, **kwargs: bool) -> FakeSpan:
        self.kwargs = kwargs
        return FakeSpan()


class FlushProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.flush_count = 0

    def force_flush(self, *, timeout_millis: int) -> None:
        assert timeout_millis == 2000
        self.flush_count += 1
        if self.fail:
            raise RuntimeError("flush failed")


def test_trace_invocation_force_flushes_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FlushProvider()
    _patch_invocation_dependencies(monkeypatch, provider)

    result = telemetry_invocation.trace_invocation(
        {"request": {"request_id": "REQ-1"}},
        lambda: {"ok": True},
    )

    assert result == {"ok": True}
    assert provider.flush_count == 1


def test_trace_invocation_preserves_interrupt_when_flush_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FlushProvider(fail=True)
    _patch_invocation_dependencies(monkeypatch, provider)

    def operation() -> None:
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        telemetry_invocation.trace_invocation({"request": {"request_id": "REQ-1"}}, operation)

    assert provider.flush_count == 1


def test_trace_node_disables_automatic_exception_status_for_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = RecordingTracer()
    monkeypatch.setattr(telemetry, "_TRACER", tracer)

    def interrupted_node(_state: dict[str, object]) -> dict[str, object]:
        raise GraphInterrupt(())

    wrapped = telemetry.trace_node("response_packager", interrupted_node)

    with pytest.raises(GraphInterrupt):
        wrapped({"request": {"request_id": "REQ-1"}})

    assert tracer.kwargs["record_exception"] is False
    assert tracer.kwargs["set_status_on_exception"] is False


@pytest.mark.parametrize(
    "record_error",
    [telemetry._record_span_error, telemetry_invocation._record_span_error],
)
def test_span_error_redacts_exception_event(
    record_error: Callable[[ErrorRecordingSpan, Exception], None],
) -> None:
    span = ErrorRecordingSpan()

    record_error(span, RuntimeError("api_key=super-secret-value user@example.com"))

    assert span.events == [
        (
            "exception",
            {
                "exception.type": "RuntimeError",
                "exception.message": "[REDACTED_SECRET] [REDACTED_EMAIL]",
                "exception.escaped": True,
            },
        ),
    ]
    assert span.status is not None
    assert span.status.description == "[REDACTED_SECRET] [REDACTED_EMAIL]"


def test_trace_invocation_redacts_automatic_sdk_exception_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        telemetry_invocation,
        "_TRACER",
        provider.get_tracer("tests.telemetry_invocation"),
    )
    monkeypatch.setattr(telemetry_invocation.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(telemetry_invocation, "emit_invocation_metric", lambda entry: None)

    def operation() -> None:
        raise RuntimeError("api_key=super-secret-value user@example.com")

    with pytest.raises(RuntimeError):
        telemetry_invocation.trace_invocation(
            {"request": {"request_id": "REQ-SECRET"}},
            operation,
        )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    events = spans[0].events
    assert len(events) == 1
    exported = f"{events[0].attributes} {spans[0].status.description}"
    assert "super-secret-value" not in exported
    assert "user@example.com" not in exported
    assert "[REDACTED_SECRET]" in exported
    assert "[REDACTED_EMAIL]" in exported


def _patch_invocation_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    provider: FlushProvider,
) -> None:
    monkeypatch.setattr(telemetry_invocation, "_TRACER", FakeTracer())
    monkeypatch.setattr(telemetry_invocation.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(telemetry_invocation, "emit_invocation_metric", lambda entry: None)
    monkeypatch.setattr(telemetry_invocation, "reset_llm_usage", lambda: 0)
    monkeypatch.setattr(telemetry_invocation, "reset_step_durations", lambda: 0)
    monkeypatch.setattr(telemetry_invocation, "reset_tool_calls", lambda: 0)
    monkeypatch.setattr(telemetry_invocation, "restore_llm_usage", lambda token: None)
    monkeypatch.setattr(telemetry_invocation, "restore_step_durations", lambda token: None)
    monkeypatch.setattr(telemetry_invocation, "restore_tool_calls", lambda token: None)
