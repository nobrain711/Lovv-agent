"""Unified State definition for LangGraph V2."""

from typing import Any, NotRequired, TypedDict


class UnifiedAgentState(TypedDict, total=False):
    """LangGraph State containing all routing flags, inputs, and intermediate results."""

    request: NotRequired[dict[str, Any]]
    intent: NotRequired[dict[str, Any]]
    profile: NotRequired[dict[str, Any]]
    festival_gate: NotRequired[dict[str, Any]]
    city_select: NotRequired[dict[str, Any]]
    planner: NotRequired[dict[str, Any]]
    response: NotRequired[dict[str, Any]]
    routing: NotRequired[dict[str, Any]]
    memory: NotRequired[dict[str, Any]]
    trace: NotRequired[dict[str, Any]]
    runtime: NotRequired[dict[str, Any]]
    itinerary_explanation_runtime: NotRequired[Any]
