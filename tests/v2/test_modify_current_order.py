from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_uses_backend_state_order_before_request_current_order() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오전 상태 장소 말고 조용한 자연 산책지로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-stale",
                        "contentId": "attraction#stale",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "프론트 stale 장소",
                        "isSeed": False,
                        "theme": "역사·전통",
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
    assert modify_intent["edit_ops"][0]["target"]["content_id"] == "attraction#state"


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
