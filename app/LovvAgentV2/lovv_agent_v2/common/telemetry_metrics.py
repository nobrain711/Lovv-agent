from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type LlmMetricPayload = dict[str, str | int | float]

DEFAULT_CONTEXT_WINDOW: Final = 200_000
TITAN_CONTEXT_WINDOW: Final = 8_192

_LLM_USAGE: ContextVar[tuple["LlmUsageMetric", ...]] = ContextVar(
    "lovv_agent_llm_usage",
    default=(),
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


def reset_llm_usage() -> Token[tuple[LlmUsageMetric, ...]]:
    return _LLM_USAGE.set(())


def restore_llm_usage(token: Token[tuple[LlmUsageMetric, ...]]) -> None:
    _LLM_USAGE.reset(token)


def llm_usage_count() -> int:
    return len(_LLM_USAGE.get())


def metrics_since(start_index: int) -> tuple[LlmUsageMetric, ...]:
    return _LLM_USAGE.get()[start_index:]


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
    "JsonValue",
    "LlmMetricPayload",
    "LlmUsageMetric",
    "aggregate_llm_metrics",
    "context_window_for_model",
    "llm_usage_count",
    "metrics_since",
    "record_llm_usage",
    "reset_llm_usage",
    "restore_llm_usage",
]
