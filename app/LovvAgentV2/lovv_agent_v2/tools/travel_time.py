"""Travel-time provider selection (ORS with Haversine fallback).

Moved from ``lovv_agent_v2.agents.planner.tools`` as part of the V2 tool code
consolidation. Fallback behavior is unchanged: when no provider is injected
and ORS is unavailable, callers still get ``HaversineTravelTimeProvider``.
"""

from __future__ import annotations

from typing import cast

from lovv_agent_v2.tools.ors_provider import (
    OrsProviderUnavailableError,
    ors_provider_from_env,
)
from lovv_agent_v2.tools.travel_time_provider import HaversineTravelTimeProvider, TravelTimeProvider


def travel_time_provider_from_value(provider: object) -> TravelTimeProvider:
    if provider is not None:
        return cast(TravelTimeProvider, provider)
    try:
        ors_provider = ors_provider_from_env()
    except OrsProviderUnavailableError:
        ors_provider = None
    if ors_provider is not None:
        return ors_provider
    return HaversineTravelTimeProvider()


__all__ = ["travel_time_provider_from_value"]
