from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type LlmMetricPayload = dict[str, str | int | float]
type DurationMetricPayload = dict[str, int | float]

DEFAULT_CONTEXT_WINDOW: Final = 200_000
TITAN_CONTEXT_WINDOW: Final = 8_192

_LLM_USAGE: ContextVar[tuple["LlmUsageMetric", ...]] = ContextVar(
    "lovv_agent_llm_usage",
    default=(),
)
_STEP_DURATIONS: ContextVar[tuple["DurationMetric", ...]] = ContextVar(
    "lovv_agent_step_durations",
    default=(),
)
_TOOL_CALLS: ContextVar[list["ToolCallMetric"] | None] = ContextVar(
    "lovv_agent_tool_calls",
    default=None,
)


@dataclass(frozen=True, slots=True)
class LlmUsageMetric:
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_window: int

    def to_log_dict(self) -> LlmMetricPayload:
        context_usage_percent = (
            round((self.total_tokens / self.context_window) * 100, 3)
            if self.context_window > 0
            else 0.0
        )
        return {
            "modelId": self.model_id,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "contextWindow": self.context_window,
            "contextUsagePercent": context_usage_percent,
        }


@dataclass(frozen=True, slots=True)
class DurationMetric:
    name: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ToolCallMetric:
    service: str
    operation: str
    duration_ms: int

    @property
    def key(self) -> str:
        return f"{self.service}.{self.operation}"


def reset_llm_usage() -> Token[tuple[LlmUsageMetric, ...]]:
    return _LLM_USAGE.set(())


def restore_llm_usage(token: Token[tuple[LlmUsageMetric, ...]]) -> None:
    _LLM_USAGE.reset(token)


def llm_usage_count() -> int:
    return len(_LLM_USAGE.get())


def metrics_since(start_index: int) -> tuple[LlmUsageMetric, ...]:
    return _LLM_USAGE.get()[start_index:]


def reset_step_durations() -> Token[tuple[DurationMetric, ...]]:
    return _STEP_DURATIONS.set(())


def restore_step_durations(token: Token[tuple[DurationMetric, ...]]) -> None:
    _STEP_DURATIONS.reset(token)


def step_durations_since(start_index: int) -> tuple[DurationMetric, ...]:
    return _STEP_DURATIONS.get()[start_index:]


def reset_tool_calls() -> Token[list[ToolCallMetric] | None]:
    return _TOOL_CALLS.set([])


def restore_tool_calls(token: Token[list[ToolCallMetric] | None]) -> None:
    _TOOL_CALLS.reset(token)


def tool_calls_since(start_index: int) -> tuple[ToolCallMetric, ...]:
    metrics = _TOOL_CALLS.get()
    if metrics is None:
        return ()
    return tuple(metrics[start_index:])


def record_llm_usage(model_id: str, usage: Mapping[str, JsonValue] | None) -> None:
    if usage is None:
        return
    metric = LlmUsageMetric(
        model_id=model_id,
        input_tokens=_int_field(usage, "inputTokens"),
        output_tokens=_int_field(usage, "outputTokens"),
        total_tokens=_int_field(usage, "totalTokens"),
        context_window=context_window_for_model(model_id),
    )
    _LLM_USAGE.set((*_LLM_USAGE.get(), metric))


def record_step_duration(name: str, duration_ms: int) -> None:
    if duration_ms < 0:
        return
    _STEP_DURATIONS.set((*_STEP_DURATIONS.get(), DurationMetric(name, duration_ms)))


def record_tool_call(service: str, operation: str, duration_ms: int) -> None:
    if duration_ms < 0:
        return
    metrics = _TOOL_CALLS.get()
    if metrics is None:
        return
    metrics.append(ToolCallMetric(service, operation, duration_ms))


def context_window_for_model(model_id: str) -> int:
    normalized = model_id.lower()
    if "titan" in normalized:
        return TITAN_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def aggregate_llm_metrics(
    metrics: tuple[LlmUsageMetric, ...],
) -> LlmMetricPayload | None:
    if not metrics:
        return None
    last = metrics[-1]
    aggregate = LlmUsageMetric(
        model_id=last.model_id,
        input_tokens=sum(metric.input_tokens for metric in metrics),
        output_tokens=sum(metric.output_tokens for metric in metrics),
        total_tokens=sum(metric.total_tokens for metric in metrics),
        context_window=last.context_window,
    )
    return aggregate.to_log_dict()


def aggregate_duration_metrics(
    metrics: tuple[DurationMetric, ...],
) -> dict[str, DurationMetricPayload] | None:
    if not metrics:
        return None
    grouped: dict[str, list[int]] = {}
    for metric in metrics:
        grouped.setdefault(metric.name, []).append(metric.duration_ms)
    return {
        name: _duration_payload(values)
        for name, values in sorted(grouped.items())
    }


def aggregate_tool_metrics(
    metrics: tuple[ToolCallMetric, ...],
) -> dict[str, DurationMetricPayload] | None:
    if not metrics:
        return None
    grouped: dict[str, list[int]] = {}
    for metric in metrics:
        grouped.setdefault(metric.key, []).append(metric.duration_ms)
    return {
        name: _duration_payload(values)
        for name, values in sorted(grouped.items())
    }


def _duration_payload(values: list[int]) -> DurationMetricPayload:
    total = sum(values)
    return {
        "count": len(values),
        "totalMs": total,
        "maxMs": max(values),
        "avgMs": round(total / len(values), 3),
    }


def _int_field(usage: Mapping[str, JsonValue], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


__all__ = [
    "DurationMetric",
    "DurationMetricPayload",
    "JsonValue",
    "LlmMetricPayload",
    "LlmUsageMetric",
    "ToolCallMetric",
    "aggregate_duration_metrics",
    "aggregate_llm_metrics",
    "aggregate_tool_metrics",
    "context_window_for_model",
    "llm_usage_count",
    "metrics_since",
    "record_llm_usage",
    "record_step_duration",
    "record_tool_call",
    "reset_llm_usage",
    "reset_step_durations",
    "reset_tool_calls",
    "restore_llm_usage",
    "restore_step_durations",
    "restore_tool_calls",
    "step_durations_since",
    "tool_calls_since",
]
