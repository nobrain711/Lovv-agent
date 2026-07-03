from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_reanchors_city_change_and_clears_stale_outputs() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "도시는 경주로 바꿔줘.",
            },
            "intent": {
                "trip_intent": {
                    "destination_id": None,
                    "raw_query": "이전 생성 입력",
                },
                "intent_output": {
                    "destination_id": None,
                    "cleaned_raw_query": "이전 생성 입력",
                },
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ("역사·전통",),
                    "include_festivals": False,
                    "cleaned_raw_query": "역사 여행",
                    "soft_preference_query": "조용한 고도 산책",
                    "destination_id": None,
                    "execution_mode": "city_discovery",
                },
            },
            "city_select": {"city_selection_result": {"selected_city": {"city_id": "KR-OLD"}}},
            "planner": {"planner_output": {"itinerary": []}},
            "response": {"response_payload": {"recommendationId": "REQ-OLD"}},
        },
    )

    intent = output["intent"]
    assert intent["city_select_input"]["destination_id"] == "KR-47-130"
    assert intent["city_select_input"]["execution_mode"] == "anchored_place_search"
    assert intent["city_select_input"]["cleaned_raw_query"] == "역사 여행"
    assert intent["city_select_input"]["soft_preference_query"] == "조용한 고도 산책"
    assert intent["trip_intent"]["destination_id"] == "KR-47-130"
    assert intent["trip_intent"]["raw_query"] == "역사 여행"
    assert intent["trip_intent"]["soft_preference_query"] == "조용한 고도 산책"
    assert "intent_output" not in intent
    assert output["city_select"] == {}
    assert output["planner"] == {}
    assert output["response"] == {}
