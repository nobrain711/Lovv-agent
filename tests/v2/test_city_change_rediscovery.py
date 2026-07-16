from __future__ import annotations

import pytest

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.supervisor.router import supervisor_node


@pytest.mark.parametrize(
    "raw_modify_query",
    ("다른 도시로 바꿔줘.", "도시 바꿔줘."),
)
def test_intent_node_builds_targetless_city_rediscovery_modify_intent(
    raw_modify_query: str,
) -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": raw_modify_query,
                "destinationId": "KR-51-170",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#old",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "기존 장소",
                        "cityId": "KR-51-170",
                    },
                ],
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ("바다·해안",),
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 바다 산책",
                    "execution_mode": "anchored_place_search",
                    "destination_id": "KR-51-170",
                },
            },
            "memory": {
                "modify_history": {
                    "excluded_city_ids": ["KR-51-150"],
                },
            },
        },
    )

    intent = output["intent"]
    city_input = intent["city_select_input"]
    modify_intent = intent["modify_intent"]
    assert modify_intent["kind"] == "city_change"
    assert modify_intent["routing_hint"] == "city_select_rediscovery"
    assert modify_intent["city_change"]["target_city_id"] is None
    assert modify_intent["city_change"]["avoid_city_ids"] == (
        "KR-51-170",
        "KR-51-150",
    )
    assert city_input["destination_id"] is None
    assert city_input["execution_mode"] == "city_discovery"
    assert city_input["disliked_city_ids"] == ("KR-51-170", "KR-51-150")
    assert city_input["preferred_city_ids"] == ()
    assert city_input["preferred_region_ids"] == ()
    assert city_input["preferred_region_spans"] == ()
    assert city_input["preferred_region_names"] == ()
    assert output["memory"]["modify_history"]["excluded_city_ids"] == (
        "KR-51-170",
        "KR-51-150",
    )


def test_named_city_in_negative_context_becomes_rediscovery_exclusion() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-negative-city",
                "itineraryRevision": "rev-negative-city",
                "rawModifyQuery": "군산 말고 다른 도시로 바꿔줘.",
                "destinationId": "KR-51-170",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#old",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "기존 장소",
                        "cityId": "KR-51-170",
                    },
                ],
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ("바다·해안",),
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 바다 산책",
                    "execution_mode": "anchored_place_search",
                    "destination_id": "KR-51-170",
                },
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    city_input = output["intent"]["city_select_input"]
    assert modify_intent["routing_hint"] == "city_select_rediscovery"
    assert modify_intent["city_change"]["target_city_id"] is None
    assert modify_intent["city_change"]["avoid_city_ids"] == (
        "KR-51-170",
        "KR-37-2",
    )
    assert city_input["disliked_city_ids"] == ("KR-51-170", "KR-37-2")


def test_unrelated_dislike_does_not_negate_named_destination() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-positive-city-with-dislike",
                "itineraryRevision": "rev-positive-city-with-dislike",
                "rawModifyQuery": "복잡한 곳은 싫어서 군산으로 도시 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#old",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "cityId": "KR-51-170",
                    },
                ],
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ("바다·해안",),
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 바다 산책",
                    "execution_mode": "anchored_place_search",
                    "destination_id": "KR-51-170",
                },
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["routing_hint"] == "planner_direct_anchor"
    assert modify_intent["city_change"]["target_city_id"] == "KR-37-2"
    assert modify_intent["city_change"]["avoid_city_ids"] == ("KR-51-170",)


def test_supervisor_routes_city_rediscovery_to_city_select() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"audit": {"skipped": True}},
            "intent": {
                "intent_type": "modification",
                "status": "ok",
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": False,
                    "destination_id": None,
                    "disliked_city_ids": ("KR-51-170",),
                },
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "city_select_rediscovery",
                    "city_change": {
                        "target_city_id": None,
                        "avoid_city_ids": ("KR-51-170",),
                    },
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "city_select"


def test_supervisor_ends_after_targetless_city_rediscovery_response() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"audit": {"skipped": True}},
            "city_select": {
                "city_selection_result": {
                    "selected_city": {"city_id": "KR-51-230", "city_name_ko": "삼척시"},
                },
            },
            "planner": {
                "planner_output": {
                    "selected_city": {"city_id": "KR-51-230", "city_name_ko": "삼척시"},
                },
            },
            "response": {
                "response_payload": {
                    "destination": {"destinationId": "KR-51-230", "name": "삼척시"},
                },
            },
            "intent": {
                "intent_type": "modification",
                "status": "ok",
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "city_select_rediscovery",
                    "city_change": {
                        "target_city_id": None,
                        "target_city_name": None,
                        "avoid_city_ids": ("KR-51-170",),
                    },
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "end"
