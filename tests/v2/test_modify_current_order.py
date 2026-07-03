from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_uses_request_current_order_before_backend_state_order() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오전 프론트 최신 장소 말고 조용한 자연 산책지로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-front",
                        "contentId": "attraction#front",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "프론트 최신 장소",
                        "isSeed": False,
                        "theme": "자연·트레킹",
                    },
                ],
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "placeId": "attraction#state",
                            "title": "상태 장소",
                            "city_id": "KR-51-150",
                            "theme_tags": ["자연·트레킹"],
                        },
                    ],
                },
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "ok"
    assert modify_intent["edit_ops"][0]["target"]["content_id"] == "attraction#front"


def test_backend_state_seed_reason_code_protects_modify_target() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오전 상태 장소 말고 조용한 자연 산책지로 바꿔줘.",
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "placeId": "attraction#seed",
                            "title": "상태 장소",
                            "city_id": "KR-51-150",
                            "theme_tags": ["역사·전통"],
                            "reason_code": "seed_floor",
                        },
                    ],
                },
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "needs_clarification"
    assert modify_intent["clarification"]["reason_code"] == "modify_seed_theme_conflict"


def test_place_modify_after_city_change_uses_front_current_order() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-city-change",
                "rawModifyQuery": "1일차 오전 강릉 최신 장소 말고 조용한 숲길로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-front-gangneung",
                        "contentId": "attraction#front-gangneung",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "강릉 최신 장소",
                        "isSeed": False,
                        "cityId": "KR-51-150",
                        "theme": "자연·트레킹",
                    },
                ],
            },
            "intent": {
                "intent_type": "modification",
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 9,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ("바다·해안",),
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 바다 산책",
                    "soft_preference_query": "한적한 해안",
                    "destination_id": "KR-51-150",
                    "execution_mode": "anchored_place_search",
                },
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "planner_direct_anchor",
                    "city_change": {"target_city_id": "KR-51-150"},
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "placeId": "attraction#stale-gangneung",
                            "title": "강릉 이전 장소",
                            "city_id": "KR-51-150",
                            "theme_tags": ["바다·해안"],
                        },
                    ],
                },
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["kind"] == "slot_replace"
    assert modify_intent["city_change"] is None
    assert modify_intent["edit_ops"][0]["target"]["content_id"] == "attraction#front-gangneung"
