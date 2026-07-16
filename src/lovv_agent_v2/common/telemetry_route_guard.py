from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from lovv_agent_v2.core.state import UnifiedAgentState

MAX_VISITED_NODES: Final = 80
REPEATED_PAIR_WARNING_COUNT: Final = 3


def record_route_visit(state: UnifiedAgentState, node_name: str) -> None:
    if not isinstance(state, dict):
        return
    trace = _trace_dict(state)
    visited = _text_tuple(trace.get("visited_nodes"))
    previous = visited[-1] if visited else ""
    next_visited = (*visited, node_name)[-MAX_VISITED_NODES:]
    trace["visited_nodes"] = list(next_visited)
    trace["route_count"] = len(next_visited)
    if previous:
        _record_pair(trace, previous, node_name)


def _trace_dict(state: UnifiedAgentState) -> dict[str, object]:
    trace_value = state.get("trace")
    if isinstance(trace_value, dict):
        return trace_value
    trace: dict[str, object] = {}
    state["trace"] = trace
    return trace


def _record_pair(trace: dict[str, object], previous: str, current: str) -> None:
    pair = f"{previous}->{current}"
    raw_counts = trace.get("route_pair_counts")
    counts = dict(raw_counts) if isinstance(raw_counts, Mapping) else {}
    count = _int_value(counts.get(pair)) + 1
    counts[pair] = count
    trace["route_pair_counts"] = counts
    if count >= REPEATED_PAIR_WARNING_COUNT:
        trace["route_loop_guard"] = {
            "reason": "repeated_node_pair",
            "repeated_pair": pair,
            "repeated_pair_count": count,
        }


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["record_route_visit"]
