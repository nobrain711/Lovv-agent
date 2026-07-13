from __future__ import annotations

from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.agents.planner.steps.route_days.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    lat: float = 37.0,
    lon: float = 127.0,
    soft_sim: float | None = None,
    subtype: str = "view",
    subtype_code: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "latitude": lat,
        "longitude": lon,
        "attraction_subtype_name": subtype,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": soft_sim if soft_sim is not None else sim,
    }
    if subtype_code is not None:
        payload["attraction_subtype_code"] = subtype_code
    return payload


def test_build_working_set_preserves_low_score_seed_without_raw_cut() -> None:
    raw_places = [
        _place("sea-1", "Sea 1", 0.90, "바다·해안"),
        _place("sea-2", "Sea 2", 0.80, "바다·해안"),
        _place("history-seed", "Old Site", 0.20, "역사·문화"),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=({"place_id": "history-seed", "theme": "역사·문화"},),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    selected_ids = [place.place_id for place in result.places]
    assert "history-seed" in selected_ids
    assert result.audit["raw_relevance_policy"] == "disabled_use_active_theme_gate"
    assert result.audit["relative_threshold"] is None
    assert result.audit["seed_preserved_count"] == 1


def test_build_working_set_adds_only_on_theme_soft_places() -> None:
    raw_places = [_place("sea-1", "Sea 1", 0.80, "바다·해안")]
    soft_places = [
        _place("history-soft", "향교", 0.10, "역사·문화", soft_sim=0.70),
        _place("nature-soft", "저수지", 0.10, "자연", soft_sim=0.90),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
            min_count=2,
        ),
    )

    selected_ids = [place.place_id for place in result.places]
    assert "history-soft" in selected_ids
    assert "nature-soft" not in selected_ids
    assert result.audit["soft_on_theme_added_count"] == 1
    assert result.audit["soft_off_theme_excluded_count"] == 1


def test_build_working_set_keeps_on_theme_soft_tail_without_relative_cut() -> None:
    raw_places = [_place("sea-1", "Sea 1", 0.80, "바다·해안")]
    soft_places = [
        _place("history-top", "향교", 0.10, "역사·전통", soft_sim=0.90),
        _place("history-tail", "고택", 0.10, "역사·전통", soft_sim=0.20),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·전통"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
            min_count=3,
        ),
    )

    assert {place.place_id for place in result.places} == {
        "sea-1",
        "history-top",
        "history-tail",
    }
    assert result.audit["soft_relevance_policy"] == "disabled_use_theme_gate"


def test_build_working_set_backfills_preferred_theme_after_active_theme() -> None:
    result = build_working_set(
        PlannerSelectionInput(
            raw_places=[
                _place("sea-1", "Sea 1", 0.90, "바다·해안"),
                _place("history-1", "History 1", 0.80, "역사·전통"),
            ],
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안",),
            secondary_themes=("역사·전통",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=2,
        ),
    )

    assert [place.place_id for place in result.places] == ["sea-1", "history-1"]
    assert result.audit["preferred_theme_backfill_count"] == 1
    assert result.audit["theme_scope_policy"] == "active_theme_primary_preferred_theme_secondary"


def test_build_working_set_blends_raw_and_soft_scores_for_anchored_overlap() -> None:
    raw_places = [
        _place("sea-anchor", "Sea Anchor", 0.80, "바다·해안"),
        _place("sea-raw", "Sea Raw", 0.85, "바다·해안"),
    ]
    soft_places = [
        _place("sea-anchor", "Sea Anchor", 0.10, "바다·해안", soft_sim=1.00),
        _place("sea-soft", "Sea Soft", 0.10, "바다·해안", soft_sim=0.70),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=({"place_id": "sea-anchor", "theme": "바다·해안"},),
            active_themes=("바다·해안",),
            theme_weights=None,
            trip_type="daytrip",
            target_count=3,
        ),
    )

    anchored = next(place for place in result.places if place.place_id == "sea-anchor")
    assert anchored.payload["raw_soft_blended_similarity"] == 0.86
    assert anchored.payload["retrieval_channels"] == ("raw", "soft")
    assert anchored.similarity == 0.80
    assert anchored.soft_similarity == 1.00
    assert result.audit["raw_soft_overlap_count"] == 1


def test_build_working_set_promotes_theme_top1_as_semantic_anchor_seed() -> None:
    raw_places = [
        _place("sea-raw", "Sea Raw", 0.90, "바다·해안", soft_sim=0.20),
        _place("sea-soft", "Sea Soft", 0.80, "바다·해안", soft_sim=1.00),
        _place("history-1", "History", 0.70, "역사·문화"),
    ]
    soft_places = [
        _place("sea-soft", "Sea Soft", 0.10, "바다·해안", soft_sim=1.00),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    seeded_ids = {place.place_id for place in result.places if place.is_seed}
    assert seeded_ids == {"sea-soft", "history-1"}
    sea_seed = next(place for place in result.places if place.place_id == "sea-soft")
    assert sea_seed.payload["seed_source"] == "theme_top1"
    assert result.audit["semantic_anchor_seed_count"] == 2
    assert result.audit["semantic_anchor_seed_policy"] == "theme_top1_after_planner_gate"


def test_build_working_set_does_not_add_semantic_anchor_when_seed_exists() -> None:
    raw_places = [
        _place("festival", "Festival", 0.20, "바다·해안"),
        _place("sea-1", "Sea", 0.90, "바다·해안"),
        _place("history-1", "History", 0.70, "역사·문화"),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=({"place_id": "festival", "theme": "바다·해안"},),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
        ),
    )

    seeded_ids = {place.place_id for place in result.places if place.is_seed}
    assert seeded_ids == {"festival"}
    assert result.audit["semantic_anchor_seed_count"] == 0


def test_build_working_set_keeps_multi_theme_gate_strict_when_below_min_count() -> None:
    raw_places = [_place("sea-1", "Sea 1", 0.80, "바다·해안")]
    soft_places = [
        _place("history-soft", "향교", 0.10, "역사·문화", soft_sim=0.70),
        _place("nature-soft", "저수지", 0.10, "자연", soft_sim=0.90),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=soft_places,
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=3,
            min_count=3,
        ),
    )

    selected_ids = [place.place_id for place in result.places]
    assert "nature-soft" not in selected_ids
    assert result.audit["no_theme_gate_added_count"] == 0
    assert result.audit["soft_off_theme_excluded_count"] == 1
    assert result.audit["no_theme_gate_policy"] == "disabled_by_v2_26_theme_scope"


def test_build_working_set_keeps_on_theme_raw_tail_without_relative_cut() -> None:
    result = build_working_set(
        PlannerSelectionInput(
            raw_places=[
                _place("nature-top", "Nature Top", 0.90, "자연"),
                _place("nature-tail-1", "Tail 1", 0.20, "자연"), _place("nature-tail-2", "Tail 2", 0.18, "자연"),
                _place("off-theme", "Museum", 0.89, "역사·문화"),
            ],
            soft_places=(), seeds=(),
            active_themes=("자연",),
            theme_weights=None, trip_type="daytrip",
            target_count=3,
        ),
    )

    assert {place.place_id for place in result.places} == {"nature-top", "nature-tail-1", "nature-tail-2"}
    assert result.audit["raw_kept_count"] == 3


def test_build_working_set_balances_requested_themes_without_profile() -> None:
    raw_places = [
        _place("sea-1", "Sea 1", 0.90, "바다·해안"),
        _place("sea-2", "Sea 2", 0.88, "바다·해안"),
        _place("sea-3", "Sea 3", 0.87, "바다·해안"),
        _place("history-1", "History 1", 0.60, "역사·문화"),
        _place("history-2", "History 2", 0.58, "역사·문화"),
        _place("history-3", "History 3", 0.57, "역사·문화"),
    ]

    result = build_working_set(
        PlannerSelectionInput(
            raw_places=raw_places,
            soft_places=(),
            seeds=(),
            active_themes=("바다·해안", "역사·문화"),
            theme_weights=None,
            trip_type="2d1n",
            target_count=4,
        ),
    )

    assert result.audit["theme_quota"] == {"바다·해안": 2, "역사·문화": 2}
    assert result.audit["theme_counts"] == {"바다·해안": 2, "역사·문화": 2}


def test_planner_subgraph_writes_v2_planner_output_from_city_select_state() -> None:
    state = {
        "intent": {
            "city_select_input": {
                "trip_type": "daytrip",
                "active_required_themes": ["바다·해안"],
                "theme_weights": None,
                "transport_pref": "walk",
                "soft_preference_query": "조용한 바다",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "country": "KR",
                    "ddb_pk": "CITY#SOKCHO",
                },
                "seeds": [
                    {
                        **_place("seed", "해변", 0.9, "바다·해안", lat=38.20, lon=128.59),
                        "theme": "바다·해안",
                        "must_include": True,
                    },
                    {
                        **_place("near", "전망대", 0.8, "바다·해안", lat=38.21, lon=128.60),
                        "theme": "바다·해안",
                        "must_include": True,
                    },
                    {
                        **_place("tail", "항구", 0.7, "바다·해안", lat=38.22, lon=128.61),
                        "theme": "바다·해안",
                        "must_include": True,
                    },
                ],
                "passthrough": {"transport_pref": "walk"},
            },
            "scoring_audit": {},
        },
    }

    result = compile_planner_subgraph().invoke(state)

    planner = result["planner"]["planner_output"]
    assert planner["validation_result"]["planner_status_gate"] == "ok"
    assert planner["itinerary"][0]["placeId"] == "seed"
    assert planner["itinerary"][0]["moveMinutes"] == 0
    assert "walk" in " ".join(planner["user_notice"])
