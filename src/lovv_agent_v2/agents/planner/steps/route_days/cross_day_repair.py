from __future__ import annotations

from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import (
    DurationLookup,
    day_travel_min,
    max_leg_min,
)


@dataclass(frozen=True, slots=True)
class RouteRepairLimits:
    hard_leg_limit_min: float
    day_limit_min: float
    soft_leg_limit_min: float | None = None


@dataclass(frozen=True, slots=True)
class RouteRepairInput:
    day_groups: tuple[tuple[PlannerPlace, ...], ...]
    reserve: tuple[PlannerPlace, ...]
    lookup: DurationLookup
    limits: RouteRepairLimits


@dataclass(frozen=True, slots=True)
class RouteRepairResult:
    day_groups: tuple[tuple[PlannerPlace, ...], ...]
    reserve: tuple[PlannerPlace, ...]
    rescued_place_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _InsertionCandidate:
    day_index: int
    places: tuple[PlannerPlace, ...]
    day_travel_min: float
    max_leg_min: float


@dataclass(frozen=True, slots=True)
class _InsertionRequest:
    place: PlannerPlace
    day_index: int
    group: tuple[PlannerPlace, ...]
    lookup: DurationLookup
    limits: RouteRepairLimits


def repair_trimmed_places(request: RouteRepairInput) -> RouteRepairResult:
    day_groups = list(request.day_groups)
    remaining: list[PlannerPlace] = []
    rescued: list[str] = []
    for place in request.reserve:
        insertion = _best_insertion(place, request, tuple(day_groups))
        if insertion is None:
            remaining.append(place)
            continue
        day_groups[insertion.day_index] = insertion.places
        rescued.append(place.place_id)
    return RouteRepairResult(
        day_groups=tuple(day_groups),
        reserve=tuple(remaining),
        rescued_place_ids=tuple(rescued),
    )


def _best_insertion(
    place: PlannerPlace,
    request: RouteRepairInput,
    day_groups: tuple[tuple[PlannerPlace, ...], ...],
) -> _InsertionCandidate | None:
    candidates = tuple(
        candidate
        for day_index, group in enumerate(day_groups)
        for candidate in _day_insertions(
            _InsertionRequest(
                place=place,
                day_index=day_index,
                group=group,
                lookup=request.lookup,
                limits=request.limits,
            ),
        )
    )
    return min(candidates, key=_insertion_sort_key, default=None)


def _day_insertions(request: _InsertionRequest) -> tuple[_InsertionCandidate, ...]:
    candidates: list[_InsertionCandidate] = []
    for index in range(1, len(request.group) + 1):
        inserted = request.group[:index] + (request.place,) + request.group[index:]
        day_minutes = day_travel_min(inserted, request.lookup)
        leg_minutes = max_leg_min(inserted, request.lookup)
        if _within_limits(day_minutes, leg_minutes, request.limits):
            candidates.append(
                _InsertionCandidate(
                    day_index=request.day_index,
                    places=inserted,
                    day_travel_min=day_minutes,
                    max_leg_min=leg_minutes,
                ),
            )
    return tuple(candidates)


def _insertion_sort_key(candidate: _InsertionCandidate) -> tuple[float, float, int]:
    return (candidate.day_travel_min, candidate.max_leg_min, candidate.day_index)


def _within_limits(day_minutes: float, leg_minutes: float, limits: RouteRepairLimits) -> bool:
    if day_minutes > limits.day_limit_min or leg_minutes > limits.hard_leg_limit_min:
        return False
    return limits.soft_leg_limit_min is None or leg_minutes <= limits.soft_leg_limit_min


__all__ = [
    "RouteRepairInput",
    "RouteRepairLimits",
    "RouteRepairResult",
    "repair_trimmed_places",
]
