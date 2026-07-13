from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace
from lovv_agent_v2.tools.travel_time_provider import DRIVING_KMH


@dataclass(frozen=True, slots=True)
class DurationLookup:
    durations: Mapping[tuple[str, str], float] | None = None

    def minutes(self, first: PlannerPlace, second: PlannerPlace) -> float:
        if self.durations is not None:
            value = self.durations.get((first.place_id, second.place_id))
            if value is not None:
                return float(value)
        return _haversine_duration_min(first, second)


def day_travel_min(places: tuple[PlannerPlace, ...], lookup: DurationLookup) -> float:
    return sum(lookup.minutes(first, second) for first, second in zip(places, places[1:]))


def max_leg_min(places: tuple[PlannerPlace, ...], lookup: DurationLookup) -> float:
    return max((lookup.minutes(first, second) for first, second in zip(places, places[1:])), default=0.0)


def travel_time_from_group(
    place: PlannerPlace,
    places: tuple[PlannerPlace, ...],
    lookup: DurationLookup,
) -> float:
    return sum(lookup.minutes(place, other) for other in places if other.place_id != place.place_id)


def _haversine_duration_min(first: PlannerPlace, second: PlannerPlace) -> float:
    if first.latitude is None or first.longitude is None:
        return math.inf
    if second.latitude is None or second.longitude is None:
        return math.inf
    return _haversine_km(first, second) / DRIVING_KMH * 60.0


def _haversine_km(first: PlannerPlace, second: PlannerPlace) -> float:
    lat1 = math.radians(first.latitude or 0.0)
    lat2 = math.radians(second.latitude or 0.0)
    delta_lat = math.radians((second.latitude or 0.0) - (first.latitude or 0.0))
    delta_lon = math.radians((second.longitude or 0.0) - (first.longitude or 0.0))
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
