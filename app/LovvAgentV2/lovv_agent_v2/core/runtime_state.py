from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InvocationRuntime:
    runtime: Mapping[str, Any] | None = None
    itinerary_explanation_runtime: Any | None = None


_CURRENT_RUNTIME: ContextVar[InvocationRuntime | None] = ContextVar(
    "lovv_agent_v2_invocation_runtime",
    default=None,
)


@contextmanager
def invocation_runtime(
    runtime: Mapping[str, Any] | None,
    itinerary_explanation_runtime: Any | None = None,
) -> Iterator[None]:
    token = _CURRENT_RUNTIME.set(
        InvocationRuntime(
            runtime=runtime,
            itinerary_explanation_runtime=itinerary_explanation_runtime,
        ),
    )
    try:
        yield
    finally:
        _CURRENT_RUNTIME.reset(token)


def runtime_value(state: Mapping[str, Any], key: str) -> Any | None:
    runtime = state.get("runtime")
    if isinstance(runtime, Mapping):
        value = runtime.get(key)
        if value is not None:
            return value
    elif runtime is not None:
        value = getattr(runtime, key, None)
        if value is not None:
            return value

    current = _CURRENT_RUNTIME.get()
    if current is None:
        return None
    if current.runtime is not None:
        value = current.runtime.get(key)
        if value is not None:
            return value
    if key == "itinerary_explanation_runtime":
        return current.itinerary_explanation_runtime
    return None


__all__ = ["InvocationRuntime", "invocation_runtime", "runtime_value"]
