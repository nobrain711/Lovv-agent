from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace, selection_sort_key
from lovv_agent_v2.agents.planner.steps.route_days.cross_day_repair import (
    RouteRepairInput,
    RouteRepairLimits,
    repair_trimmed_places,
)
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import (
    day_place_targets,
    min_day_place_targets,
    trip_day_count,
)
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import (
    DurationLookup,
)
from lovv_agent_v2.agents.planner.steps.route_days.trim_policy import (
    RouteTrimLimits,
    route_trim_limits,
    trim_over_limit,
)


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


def route_days(
    places: Sequence[PlannerPlace],
    *,
    trip_type: str,
    transport_pref: str,
    durations: Mapping[tuple[str, str], float] | None = None,
    provider_audit: Mapping[str, object] | None = None,
) -> RoutingResult:
    lookup = DurationLookup(durations)
    limits = route_trim_limits(transport_pref)
    if not places:
        return RoutingResult(days=(), reserve=(), audit=_audit(transport_pref, False, (), provider_audit, limits))
    day_count = trip_day_count(trip_type)
    sorted_places = tuple(sorted(places, key=_sort_key, reverse=True))
    anchors = _anchors(sorted_places, day_count, lookup)
    day_targets = day_place_targets(trip_type, len(anchors))
    day_min_targets = min_day_place_targets(trip_type, len(anchors))
    assignments = _assign_to_anchor_days(sorted_places, anchors, lookup, day_targets)
    reserve: list[PlannerPlace] = []
    day_groups: list[tuple[PlannerPlace, ...]] = []
    for index, anchor in enumerate(anchors, start=1):
        assigned = assignments.get(anchor.place_id, (anchor,))
        ordered = _nearest_neighbor_order(assigned, anchor, lookup)
        kept, trimmed = trim_over_limit(
            ordered,
            lookup,
            min_places=day_min_targets[index - 1],
            limits=limits,
        )
        reserve.extend(trimmed)
        day_groups.append(kept)
    repair = repair_trimmed_places(
        RouteRepairInput(
            day_groups=tuple(day_groups),
            reserve=tuple(reserve),
            lookup=lookup,
            limits=RouteRepairLimits(
                hard_leg_limit_min=limits.hard_leg_limit_min,
                day_limit_min=limits.day_limit_min,
                soft_leg_limit_min=limits.soft_leg_limit_min,
            ),
        ),
    )
    days: list[RouteDay] = []
    for index, anchor in enumerate(anchors, start=1):
        routed = _routed_places(repair.day_groups[index - 1], lookup)
        days.append(
            RouteDay(
                day=index,
                anchor_place_id=anchor.place_id,
                anchor_type="seed" if anchor.is_seed else "medoid",
                places=routed,
                day_travel_min=sum(place.move_min_from_prev for place in routed),
            ),
        )
    audit = _audit(transport_pref, _is_compact(days), repair.reserve, provider_audit, limits)
    audit["day_place_targets"] = day_targets
    audit["day_min_place_targets"] = day_min_targets
    audit["place_density_policy"] = "edge_days_lighter"
    audit["trim_floor_policy"] = "preserve_min_day_place_targets"
    audit["cross_day_rescued_place_ids"] = repair.rescued_place_ids
    return RoutingResult(days=tuple(days), reserve=repair.reserve, audit=audit)


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
    day_targets: Sequence[int],
) -> dict[str, tuple[PlannerPlace, ...]]:
    buckets: dict[str, list[PlannerPlace]] = {anchor.place_id: [anchor] for anchor in anchors}
    target_by_anchor = {
        anchor.place_id: max(day_targets[index], 1)
        for index, anchor in enumerate(anchors)
    }
    anchor_ids = set(buckets)
    for place in places:
        if place.place_id in anchor_ids:
            continue
        anchor = min(
            anchors,
            key=lambda item: (
                len(buckets[item.place_id]) >= target_by_anchor[item.place_id],
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
    return tuple(ordered)


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
    limits: RouteTrimLimits,
) -> dict[str, object]:
    notice = "walkable_compact_city" if transport_pref == "walk" and compact_walkable else ""
    if transport_pref == "walk" and not compact_walkable:
        notice = "walking_preference_requires_transit_or_car"
    audit: dict[str, object] = {
        "duration_unit": "minutes",
        "duration_profile": "driving",
        "fallback_used": "haversine_duration",
        "max_leg_min": limits.soft_leg_limit_min,
        "soft_leg_limit_min": limits.soft_leg_limit_min,
        "day_limit_min": limits.day_limit_min,
        "hard_leg_limit_min": limits.hard_leg_limit_min,
        "outlier_anchor_policy": "medoid_not_farthest",
        "transport_notice": notice,
        "trimmed_place_ids": [place.place_id for place in reserve],
    }
    if provider_audit is not None:
        audit.update(provider_audit)
    return audit


def _sort_key(place: PlannerPlace) -> tuple[bool, float, float, float]:
    return selection_sort_key(place)
