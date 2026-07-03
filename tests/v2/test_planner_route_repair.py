from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.route_days.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)
from lovv_agent_v2.agents.planner.steps.route_days.routing import route_days


def _place(place_id: str, title: str, sim: float, theme: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "latitude": 37.0,
        "longitude": 127.0,
        "attraction_subtype_name": "view",
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": sim,
    }


def test_route_days_preserves_min_day_places_when_trimming_long_routes() -> None:
    places = (
        _place("seed", "Anchor", 0.9, "바다·해안"),
        _place("near", "Near", 0.8, "바다·해안"),
        _place("far", "Far", 0.7, "바다·해안"),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=({"place_id": "seed", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=3,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="walk",
        durations={
            ("seed", "near"): 80.0,
            ("near", "far"): 80.0,
            ("seed", "far"): 160.0,
        },
    )

    assert len(routed.days[0].places) == 2
    assert len(routed.reserve) == 1
    assert routed.audit["day_limit_min"] == 180.0
    assert routed.audit["day_min_place_targets"] == (2,)
    assert routed.audit["trim_floor_policy"] == "preserve_min_day_place_targets"


def test_route_days_applies_soft_leg_limit_only_for_walk() -> None:
    places = (
        _place("seed", "Anchor", 0.9, "바다·해안"),
        _place("near", "Near", 0.8, "바다·해안"),
        _place("far", "Far", 0.7, "바다·해안"),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=({"place_id": "seed", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=3,
        ),
    )
    durations = {
        ("seed", "near"): 80.0,
        ("near", "far"): 30.0,
        ("seed", "far"): 100.0,
    }

    car_route = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="car",
        durations=durations,
    )
    walk_route = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="walk",
        durations=durations,
    )

    assert len(car_route.days[0].places) == 3
    assert car_route.audit["soft_leg_limit_min"] is None
    assert len(walk_route.days[0].places) == 2
    assert walk_route.audit["soft_leg_limit_min"] == 60.0


def test_route_days_trims_extreme_leg_even_below_min_day_places() -> None:
    places = (
        _place("seed", "Anchor", 0.9, "바다·해안"),
        _place("island", "Extreme Island", 0.8, "바다·해안"),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=({"place_id": "seed", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=2,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="daytrip",
        transport_pref="car",
        durations={("seed", "island"): 408.0},
    )

    assert tuple(place.place_id for place in routed.reserve) == ("island",)
    assert tuple(place.place.place_id for place in routed.days[0].places) == ("seed",)
    assert routed.audit["hard_leg_limit_min"] == 120.0


def test_route_days_reinserts_trimmed_place_into_better_day() -> None:
    places = (
        _place("seed-a", "Anchor A", 0.99, "바다·해안"),
        _place("seed-b", "Anchor B", 0.98, "바다·해안"),
        _place("a-1", "A Near", 0.97, "바다·해안"),
        _place("b-1", "B Near 1", 0.96, "바다·해안"),
        _place("b-2", "B Near 2", 0.95, "바다·해안"),
        _place("rescue", "Better On Day B", 0.94, "바다·해안"),
    )
    working_set = build_working_set(
        PlannerSelectionInput(
            raw_places=places,
            soft_places=(),
            seeds=(
                {"place_id": "seed-a", "theme": "바다·해안"},
                {"place_id": "seed-b", "theme": "바다·해안"},
            ),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="2d1n",
            target_count=6,
        ),
    )

    routed = route_days(
        working_set.places,
        trip_type="2d1n",
        transport_pref="walk",
        durations={
            ("seed-a", "a-1"): 10.0,
            ("seed-a", "b-1"): 100.0,
            ("seed-a", "b-2"): 100.0,
            ("seed-a", "rescue"): 100.0,
            ("seed-b", "a-1"): 100.0,
            ("seed-b", "b-1"): 10.0,
            ("seed-b", "b-2"): 20.0,
            ("seed-b", "rescue"): 10.0,
            ("a-1", "rescue"): 100.0,
            ("rescue", "b-1"): 10.0,
            ("rescue", "b-2"): 20.0,
            ("b-1", "b-2"): 10.0,
        },
    )

    day_place_ids = tuple(
        tuple(routed_place.place.place_id for routed_place in day.places)
        for day in routed.days
    )
    assert "rescue" in day_place_ids[1]
    assert "rescue" not in {place.place_id for place in routed.reserve}
    assert routed.audit["cross_day_rescued_place_ids"] == ("rescue",)
