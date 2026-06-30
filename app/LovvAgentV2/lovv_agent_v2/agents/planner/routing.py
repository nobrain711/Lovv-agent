from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.place_selection import PlannerPlace
from lovv_agent_v2.agents.planner.travel_time import DRIVING_KMH

MAX_DRIVE_LEG_MIN = 60.0
MAX_DRIVE_DAY_MIN = 150.0
TRIP_DAY_COUNTS = {
    "daytrip": 1,
    "2d1n": 2,
    "3d2n": 3,
}


@dataclass(frozen=True, slots=True)
class RoutedPlace:
    place: PlannerPlace
    move_min_from_prev: int


@dataclass(frozen=True, slots=True)
class RouteDay:
    day: int
    anchor_place_id: str
    anchor_type: str
    places: tuple[RoutedPlace, ...]
    day_travel_min: int


@dataclass(frozen=True, slots=True)
class RoutingResult:
    days: tuple[RouteDay, ...]
    reserve: tuple[PlannerPlace, ...]
    audit: dict[str, object]


@dataclass(frozen=True, slots=True)
class DurationLookup:
    durations: Mapping[tuple[str, str], float] | None = None

    def minutes(self, first: PlannerPlace, second: PlannerPlace) -> float:
        if self.durations is not None:
            value = self.durations.get((first.place_id, second.place_id))
            if value is not None:
                return float(value)
        return _haversine_duration_min(first, second)


def route_days(
    places: Sequence[PlannerPlace],
    *,
    trip_type: str,
    transport_pref: str,
    durations: Mapping[tuple[str, str], float] | None = None,
    provider_audit: Mapping[str, object] | None = None,
) -> RoutingResult:
    lookup = DurationLookup(durations)
    if not places:
        return RoutingResult(days=(), reserve=(), audit=_audit(transport_pref, False, (), provider_audit))
    day_count = TRIP_DAY_COUNTS.get(trip_type, 3)
    sorted_places = tuple(sorted(places, key=_sort_key, reverse=True))
    anchors = _anchors(sorted_places, day_count, lookup)
    assignments = _assign_to_anchor_days(sorted_places, anchors, lookup)
    reserve: list[PlannerPlace] = []
    days: list[RouteDay] = []
    for index, anchor in enumerate(anchors, start=1):
        assigned = assignments.get(anchor.place_id, (anchor,))
        ordered = _nearest_neighbor_order(assigned, anchor, lookup)
        kept, trimmed = _trim_over_limit(ordered, lookup)
        reserve.extend(trimmed)
        routed = _routed_places(kept, lookup)
        days.append(
            RouteDay(
                day=index,
                anchor_place_id=anchor.place_id,
                anchor_type="seed" if anchor.is_seed else "medoid",
                places=routed,
                day_travel_min=sum(place.move_min_from_prev for place in routed),
            ),
        )
    audit = _audit(transport_pref, _is_compact(days), tuple(reserve), provider_audit)
    return RoutingResult(days=tuple(days), reserve=tuple(reserve), audit=audit)


def _anchors(
    places: Sequence[PlannerPlace],
    day_count: int,
    lookup: DurationLookup,
) -> tuple[PlannerPlace, ...]:
    seeds = tuple(place for place in places if place.is_seed)
    anchors = list(seeds[:day_count])
    candidates = [place for place in places if place.place_id not in {a.place_id for a in anchors}]
    while len(anchors) < day_count and candidates:
        medoid = _medoid(candidates, lookup)
        anchors.append(medoid)
        candidates.remove(medoid)
    return tuple(anchors) if anchors else (places[0],)


def _assign_to_anchor_days(
    places: Sequence[PlannerPlace],
    anchors: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> dict[str, tuple[PlannerPlace, ...]]:
    capacity = max(math.ceil(len(places) / len(anchors)), 1)
    buckets: dict[str, list[PlannerPlace]] = {anchor.place_id: [anchor] for anchor in anchors}
    anchor_ids = set(buckets)
    for place in places:
        if place.place_id in anchor_ids:
            continue
        anchor = min(
            anchors,
            key=lambda item: (
                len(buckets[item.place_id]) >= capacity,
                lookup.minutes(item, place),
                len(buckets[item.place_id]),
            ),
        )
        buckets[anchor.place_id].append(place)
    return {place_id: tuple(bucket) for place_id, bucket in buckets.items()}


def _nearest_neighbor_order(
    places: Sequence[PlannerPlace],
    anchor: PlannerPlace,
    lookup: DurationLookup,
) -> tuple[PlannerPlace, ...]:
    remaining = [place for place in places if place.place_id != anchor.place_id]
    ordered = [anchor]
    while remaining:
        previous = ordered[-1]
        next_place = min(remaining, key=lambda place: lookup.minutes(previous, place))
        ordered.append(next_place)
        remaining.remove(next_place)
    return tuple(_time_of_day_adjusted(ordered))


def _time_of_day_adjusted(places: Sequence[PlannerPlace]) -> tuple[PlannerPlace, ...]:
    morning = [place for place in places if _has_keyword(place, ("일출", "sunrise"))]
    evening = [place for place in places if _has_keyword(place, ("낙조", "야경", "sunset", "night"))]
    middle = [
        place
        for place in places
        if place.place_id not in {item.place_id for item in (*morning, *evening)}
    ]
    return tuple((*morning, *middle, *evening))


def _trim_over_limit(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> tuple[tuple[PlannerPlace, ...], tuple[PlannerPlace, ...]]:
    kept = list(places)
    trimmed: list[PlannerPlace] = []
    while len(kept) > 1 and (
        _day_travel_min(kept, lookup) > MAX_DRIVE_DAY_MIN or _max_leg_min(kept, lookup) > MAX_DRIVE_LEG_MIN
    ):
        candidate = _leg_limit_candidate(kept, lookup)
        if candidate is None:
            candidate = max(
                (place for place in kept if not place.is_seed),
                key=lambda place: _distance_from_group(place, kept, lookup),
                default=None,
            )
        if candidate is None:
            break
        kept.remove(candidate)
        trimmed.append(candidate)
    return tuple(kept), tuple(trimmed)


def _routed_places(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> tuple[RoutedPlace, ...]:
    routed: list[RoutedPlace] = []
    previous: PlannerPlace | None = None
    for place in places:
        move_min = 0 if previous is None else round(lookup.minutes(previous, place))
        routed.append(RoutedPlace(place=place, move_min_from_prev=move_min))
        previous = place
    return tuple(routed)


def _medoid(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> PlannerPlace:
    return min(
        places,
        key=lambda place: (
            sum(lookup.minutes(place, other) for other in places),
            -place.similarity,
        ),
    )


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


def _day_travel_min(places: Sequence[PlannerPlace], lookup: DurationLookup) -> float:
    return sum(lookup.minutes(first, second) for first, second in zip(places, places[1:]))


def _max_leg_min(places: Sequence[PlannerPlace], lookup: DurationLookup) -> float:
    return max((lookup.minutes(first, second) for first, second in zip(places, places[1:])), default=0.0)


def _leg_limit_candidate(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> PlannerPlace | None:
    worst_pair = max(
        zip(places, places[1:]),
        key=lambda pair: lookup.minutes(pair[0], pair[1]),
        default=None,
    )
    if worst_pair is None or lookup.minutes(worst_pair[0], worst_pair[1]) <= MAX_DRIVE_LEG_MIN:
        return None
    removable = tuple(place for place in worst_pair if not place.is_seed)
    if not removable:
        return None
    return min(removable, key=_sort_key)


def _distance_from_group(
    place: PlannerPlace,
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> float:
    return sum(lookup.minutes(place, other) for other in places if other.place_id != place.place_id)


def _is_compact(days: Sequence[RouteDay]) -> bool:
    leg_minutes = [
        routed.move_min_from_prev
        for day in days
        for routed in day.places
        if routed.move_min_from_prev > 0
    ]
    return bool(leg_minutes) and max(leg_minutes) <= 30


def _audit(
    transport_pref: str,
    compact_walkable: bool,
    reserve: Sequence[PlannerPlace],
    provider_audit: Mapping[str, object] | None,
) -> dict[str, object]:
    notice = "walkable_compact_city" if transport_pref == "walk" and compact_walkable else ""
    if transport_pref == "walk" and not compact_walkable:
        notice = "walking_preference_requires_transit_or_car"
    audit: dict[str, object] = {
        "duration_unit": "minutes",
        "duration_profile": "driving",
        "fallback_used": "haversine_duration",
        "max_leg_min": MAX_DRIVE_LEG_MIN,
        "day_limit_min": MAX_DRIVE_DAY_MIN,
        "outlier_anchor_policy": "medoid_not_farthest",
        "transport_notice": notice,
        "trimmed_place_ids": [place.place_id for place in reserve],
    }
    if provider_audit is not None:
        audit.update(provider_audit)
    return audit


def _sort_key(place: PlannerPlace) -> tuple[bool, float, float]:
    return (place.is_seed, place.soft_similarity, place.similarity)


def _has_keyword(place: PlannerPlace, keywords: Sequence[str]) -> bool:
    title = place.title.casefold()
    return any(keyword.casefold() in title for keyword in keywords)
