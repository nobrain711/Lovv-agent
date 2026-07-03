from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace, selection_sort_key
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import (
    DurationLookup,
    day_travel_min,
    max_leg_min,
    travel_time_from_group,
)

MAX_WALK_LEG_MIN = 60.0
MAX_DRIVE_DAY_MIN = 180.0
MAX_HARD_LEG_MIN = 120.0


@dataclass(frozen=True, slots=True)
class RouteTrimLimits:
    day_limit_min: float
    hard_leg_limit_min: float
    soft_leg_limit_min: float | None


def route_trim_limits(transport_pref: str) -> RouteTrimLimits:
    return RouteTrimLimits(
        day_limit_min=MAX_DRIVE_DAY_MIN,
        hard_leg_limit_min=MAX_HARD_LEG_MIN,
        soft_leg_limit_min=MAX_WALK_LEG_MIN if transport_pref == "walk" else None,
    )


def trim_over_limit(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
    *,
    min_places: int,
    limits: RouteTrimLimits,
) -> tuple[tuple[PlannerPlace, ...], tuple[PlannerPlace, ...]]:
    kept = list(places)
    trimmed: list[PlannerPlace] = []
    while len(kept) > 1 and max_leg_min(tuple(kept), lookup) > limits.hard_leg_limit_min:
        candidate = _leg_limit_candidate(kept, lookup, leg_limit_min=limits.hard_leg_limit_min)
        if candidate is None:
            break
        kept.remove(candidate)
        trimmed.append(candidate)
    floor = max(min_places, 1)
    while len(kept) > floor and (
        day_travel_min(tuple(kept), lookup) > limits.day_limit_min
        or _over_soft_leg_limit(tuple(kept), lookup, limits.soft_leg_limit_min)
    ):
        candidate = (
            _leg_limit_candidate(kept, lookup, leg_limit_min=limits.soft_leg_limit_min)
            if limits.soft_leg_limit_min is not None
            else None
        )
        if candidate is None:
            candidate = max(
                (place for place in kept if not place.is_seed),
                key=lambda place: travel_time_from_group(place, tuple(kept), lookup),
                default=None,
            )
        if candidate is None:
            break
        kept.remove(candidate)
        trimmed.append(candidate)
    return tuple(kept), tuple(trimmed)


def _leg_limit_candidate(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
    *,
    leg_limit_min: float,
) -> PlannerPlace | None:
    worst_pair = max(
        zip(places, places[1:]),
        key=lambda pair: lookup.minutes(pair[0], pair[1]),
        default=None,
    )
    if worst_pair is None or lookup.minutes(worst_pair[0], worst_pair[1]) <= leg_limit_min:
        return None
    removable = tuple(place for place in worst_pair if not place.is_seed)
    if not removable:
        return None
    return min(removable, key=selection_sort_key)


def _over_soft_leg_limit(
    places: tuple[PlannerPlace, ...],
    lookup: DurationLookup,
    soft_leg_limit: float | None,
) -> bool:
    return soft_leg_limit is not None and max_leg_min(places, lookup) > soft_leg_limit


__all__ = ["RouteTrimLimits", "route_trim_limits", "trim_over_limit"]
