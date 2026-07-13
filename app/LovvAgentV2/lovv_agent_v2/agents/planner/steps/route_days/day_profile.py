from __future__ import annotations

from collections.abc import Mapping
from typing import Final

DEFAULT_DAY_PLACE_MAX_TARGETS: Final[tuple[int, ...]] = (3, 4, 3)
DEFAULT_DAY_PLACE_MIN_TARGETS: Final[tuple[int, ...]] = (2, 3, 2)
TRIP_DAY_PLACE_MAX_TARGETS: Final[Mapping[str, tuple[int, ...]]] = {
    "daytrip": (3,),
    "2d1n": (3, 3),
    "3d2n": DEFAULT_DAY_PLACE_MAX_TARGETS,
}
TRIP_DAY_PLACE_MIN_TARGETS: Final[Mapping[str, tuple[int, ...]]] = {
    "daytrip": (2,),
    "2d1n": (2, 2),
    "3d2n": DEFAULT_DAY_PLACE_MIN_TARGETS,
}


def day_place_targets(trip_type: str, day_count: int | None = None) -> tuple[int, ...]:
    return _targets(TRIP_DAY_PLACE_MAX_TARGETS, DEFAULT_DAY_PLACE_MAX_TARGETS, trip_type, day_count)


def min_day_place_targets(trip_type: str, day_count: int | None = None) -> tuple[int, ...]:
    return _targets(TRIP_DAY_PLACE_MIN_TARGETS, DEFAULT_DAY_PLACE_MIN_TARGETS, trip_type, day_count)


def _targets(
    profiles: Mapping[str, tuple[int, ...]],
    default_targets: tuple[int, ...],
    trip_type: str,
    day_count: int | None,
) -> tuple[int, ...]:
    targets = profiles.get(trip_type, default_targets)
    if day_count is None or day_count == len(targets):
        return targets
    if day_count <= 0:
        return ()
    if day_count < len(targets):
        return targets[:day_count]
    return targets + (targets[-1],) * (day_count - len(targets))


def trip_day_count(trip_type: str) -> int:
    return len(day_place_targets(trip_type))


def trip_place_target(trip_type: str) -> int:
    return sum(day_place_targets(trip_type))


def trip_min_place_target(trip_type: str) -> int:
    return sum(min_day_place_targets(trip_type))


def bounded_min_place_target(trip_type: str, target_count: int, override: int | None = None) -> int:
    min_count = trip_min_place_target(trip_type) if override is None else override
    return min(min_count, target_count)


def slot_label_for_order(day_number: int, day_count: int, order: int, count: int) -> str:
    if day_count > 1 and day_number == 1:
        return "evening" if order == count and count > 1 else "afternoon"
    if day_count > 1 and day_number == day_count:
        return "morning" if order == 1 else "afternoon"
    if order == 1:
        return "morning"
    if order == count:
        return "evening"
    return "afternoon"
