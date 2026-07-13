from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.tools.city_select_contracts import (
    AttractionCandidate,
    PrunedCityGroups,
    prepare_city_select_context,
)
from lovv_agent_v2.agents.city_select.nodes import scoring_and_selection_node
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool


def _candidate(
    place_id: str,
    distance: float,
    *,
    subtype_code: str = "NA020900",
) -> AttractionCandidate:
    return AttractionCandidate(
        key=place_id,
        place_id=place_id,
        distance=distance,
        entity_type="attraction",
        city_id="KR-TEST",
        city_name_ko="테스트시",
        title=f"장소 {place_id}",
        theme_tags=("바다·해안",),
        latitude=35.0 + distance,
        longitude=129.0 + distance,
        ddb_pk="CITY#TEST",
        ddb_sk=f"ATTRACTION#{place_id}",
        metadata={"attraction_subtype_code": subtype_code},
    )


def test_scoring_node_packages_no_festival_path_without_seed_result(
    monkeypatch: Any,
) -> None:
    def city_visitor_stats(
        self: DynamoLookupTool,
        city_ids: Sequence[str],
        travel_month: int,
        *,
        partition_key_by_city: Mapping[str, str] | None = None,
    ) -> dict[str, float | None]:
        return {city_id: None for city_id in city_ids}

    monkeypatch.setattr(DynamoLookupTool, "city_visitor_stats", city_visitor_stats)
    context = prepare_city_select_context(
        {
            "country": "KR",
            "travel_month": 9,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["바다·해안"],
            "include_festivals": False,
            "cleaned_raw_query": "조용한 바다",
            "soft_preference_query": "",
            "unsupported_conditions": [],
            "destination_id": None,
            "user_location": None,
            "execution_mode": "city_discovery",
            "congestion_pref": "quiet",
            "transport_pref": "unknown",
        },
    )
    state = {
        "city_select": {
            "scratch": {
                "pruned_groups": PrunedCityGroups(
                    survived_groups={
                        "KR-TEST": (
                            _candidate("P1", 0.10),
                            _candidate("P2", 0.20),
                        ),
                    },
                    eliminated_cities=(),
                ),
                "festival_seed_result": None,
                "context": context,
                "retrieved_count": 2,
                "merged_count": 2,
            },
        },
    }

    result = scoring_and_selection_node(state)

    city_select = result["city_select"]
    city_result = city_select["city_selection_result"]
    coverage = city_select["scoring_audit"]["coverage_audit"]
    fallback_audit = city_select["scoring_audit"]["fallback_audit"]
    assert city_result["selected_city"]["city_id"] == "KR-TEST"
    assert city_select["scoring_audit"]["selected_festival_candidates"] == []
    assert "recommended_places" not in city_select["scoring_audit"]
    assert "recommended_places_by_city" not in city_select["scoring_audit"]
    assert "selected_city_rank" not in fallback_audit
    assert "city_reselected_for_itinerary_capacity" not in fallback_audit
    assert "reserve_places" not in city_select["scoring_audit"]
    assert "reserve_places_by_city" not in city_select["scoring_audit"]
    assert "reserve_theme_counts" not in coverage
    assert "reserve_budget" not in coverage
    assert "reserve_places_considered" not in coverage
    assert "scratch" not in city_select
    assert "pruned_groups" not in city_select
    assert "context" not in city_select
    assert "festival_seed_result" not in city_select
    assert "selected_destination" not in city_select


def test_scoring_node_preserves_subtype_metadata_for_planner_handoff(
    monkeypatch: Any,
) -> None:
    def city_visitor_stats(
        self: DynamoLookupTool,
        city_ids: Sequence[str],
        travel_month: int,
        *,
        partition_key_by_city: Mapping[str, str] | None = None,
    ) -> dict[str, float | None]:
        return {city_id: None for city_id in city_ids}

    monkeypatch.setattr(DynamoLookupTool, "city_visitor_stats", city_visitor_stats)
    context = prepare_city_select_context(
        {
            "country": "KR",
            "travel_month": 9,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["바다·해안"],
            "include_festivals": False,
            "cleaned_raw_query": "조용한 바다",
            "soft_preference_query": "",
            "unsupported_conditions": [],
            "destination_id": None,
            "user_location": None,
            "execution_mode": "city_discovery",
            "congestion_pref": "quiet",
            "transport_pref": "unknown",
        },
    )
    state = {
        "city_select": {
            "scratch": {
                "pruned_groups": PrunedCityGroups(
                    survived_groups={
                        "KR-TEST": (
                            _candidate("P1", 0.10, subtype_code="NA020900"),
                            _candidate("P2", 0.20, subtype_code="NA020700"),
                        ),
                    },
                    eliminated_cities=(),
                ),
                "festival_seed_result": None,
                "context": context,
                "retrieved_count": 2,
                "merged_count": 2,
            },
        },
    }

    result = scoring_and_selection_node(state)

    seeds = result["city_select"]["city_selection_result"]["seeds"]
    assert seeds[0]["attraction_subtype_code"] == "NA020900"
    assert "attraction_subtype_name" not in seeds[0]
    assert "lcls_systm3" not in seeds[0]
