from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from math import inf
from typing import Any


def weather_sensitive_targets(
    itinerary: Sequence[Mapping[str, Any]],
    sensitive_exposures: set[str],
    item_exposure,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, item in enumerate(itinerary)
        if item_exposure(item) in sensitive_exposures
    )


def replacement_combinations(
    itinerary: Sequence[Mapping[str, Any]],
    targets: Sequence[int],
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    limited = tuple(candidates[:limit])
    seed_index = _seed_target_index(itinerary, targets)
    if seed_index is None:
        return tuple(combinations(limited, len(targets)))
    seed_candidate = _medoid_candidate(_day_items(itinerary, _day(itinerary[seed_index])), limited)
    if seed_candidate is None:
        return ()
    remaining_targets = tuple(index for index in targets if index != seed_index)
    remaining_candidates = tuple(candidate for candidate in limited if _place_id(candidate) != _place_id(seed_candidate))
    combos: list[tuple[Mapping[str, Any], ...]] = []
    for replacements in combinations(remaining_candidates, len(remaining_targets)):
        replacement_by_target = dict(zip(remaining_targets, replacements, strict=False))
        replacement_by_target[seed_index] = seed_candidate
        combos.append(tuple(replacement_by_target[index] for index in targets))
    return tuple(combos)


def _seed_target_index(
    itinerary: Sequence[Mapping[str, Any]],
    targets: Sequence[int],
) -> int | None:
    for index in targets:
        item = itinerary[index]
        if item.get("isSeed") is True or item.get("is_seed") is True:
            return index
    return None


def _medoid_candidate(
    day_items: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: _distance_to_day_center(candidate, day_items))


def _distance_to_day_center(
    candidate: Mapping[str, Any],
    day_items: Sequence[Mapping[str, Any]],
) -> float:
    candidate_point = _lat_lon(candidate)
    points = tuple(point for item in day_items if (point := _lat_lon(item)) is not None)
    if candidate_point is None or not points:
        return inf
    center_lat = sum(point[0] for point in points) / len(points)
    center_lon = sum(point[1] for point in points) / len(points)
    return abs(candidate_point[0] - center_lat) + abs(candidate_point[1] - center_lon)


def _day_items(items: Sequence[Mapping[str, Any]], day: int) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in items if _day(item) == day)


def _lat_lon(item: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = _float(item.get("latitude", item.get("lat")))
    lon = _float(item.get("longitude", item.get("lon", item.get("lng"))))
    if lat is None or lon is None:
        return None
    return lat, lon


def _float(value: Any) -> float | None:
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) else None


def _day(item: Mapping[str, Any]) -> int:
    value = item.get("day")
    return value if isinstance(value, int) and not isinstance(value, bool) else 1


def _place_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("place_id", item.get("placeId", item.get("contentId")))
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["replacement_combinations", "weather_sensitive_targets"]
