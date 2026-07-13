from __future__ import annotations

from lovv_agent_v2.agents.mock_contract.nodes import mock_intent_node, mock_profile_node
from lovv_agent_v2.core.mock_graph import compile_v2_mock_graph


def test_mock_intent_node_normalizes_front_request() -> None:
    state = {
        "request": {
            "request_id": "case-1",
            "country": "KR",
            "travel_month": 9,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["바다·해안"],
            "include_festivals": False,
            "cleaned_raw_query": "조용한 바다",
            "soft_preference_query": "한적한 해안",
            "destination_id": None,
            "user_location": None,
        },
        "intent": {},
        "profile": {},
    }

    result = mock_intent_node(state)

    city_input = result["intent"]["city_select_input"]
    assert city_input["active_required_themes"] == ("바다·해안",)
    assert city_input["cleaned_raw_query"] == "조용한 바다"
    assert result["intent"]["trip_intent"]["raw_query"] == "조용한 바다"
    assert result["intent"]["intent_mode"] == "mock_generation"


def test_mock_profile_node_applies_db_like_profile_record() -> None:
    state = {
        "intent": {
            "city_select_input": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ("바다·해안", "자연·트레킹"),
                "include_festivals": False,
                "cleaned_raw_query": "바다와 숲",
                "destination_id": None,
                "user_location": None,
            },
        },
        "profile": {
            "profile_record": {
                "profile_id": "P05_three_trips_sea_threshold",
                "lovv_user_profile": {
                    "saved_trip_count": 3,
                    "saved_theme_counts": {
                        "sea_coast": 3,
                        "nature_trekking": 0,
                        "history_tradition": 0,
                        "art_sense": 0,
                        "healing_rest": 0,
                    },
                },
            },
        },
    }

    result = mock_profile_node(state)

    city_input = result["intent"]["city_select_input"]
    assert city_input["theme_weights"] == {"바다·해안": 1.3, "자연·트레킹": 0.8}
    assert result["profile"]["audit"]["profile_active"] is True
    assert result["profile"]["applied_persona_id"] == "P05_three_trips_sea_threshold"


def test_mock_graph_records_confirmation_without_production_intent_profile() -> None:
    graph = compile_v2_mock_graph()

    result = graph.invoke(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
            "profile": {},
        },
    )

    assert result["intent"]["intent_mode"] == "mock_passthrough"
    assert result["profile"]["profile_update"]["reason"] == "itinerary_confirmed"
    assert result["routing"]["next_node"] == "end"
