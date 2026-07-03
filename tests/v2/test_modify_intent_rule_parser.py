from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_blocks_cross_theme_seed_replace_modify_intent() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오전 시드 장소 말고 자연 산책지로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#seed",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "시드 장소",
                        "isSeed": True,
                        "theme": "역사·전통",
                    },
                ],
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "needs_clarification"
    assert modify_intent["edit_ops"] == []
    assert modify_intent["clarification"]["reason_code"] == "modify_seed_theme_conflict"
    assert modify_intent["routing_hint"] == "response_packager_wait_user"


def test_intent_node_builds_multiple_slot_replace_modify_intent() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": (
                    "1일차 오전은 조용한 숲길로 바꾸고 "
                    "1일차 오후는 실내 전시 공간으로 바꿔줘."
                ),
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#morning",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "오전 장소",
                        "isSeed": False,
                        "theme": "바다·해안",
                    },
                    {
                        "itemId": "item-2",
                        "contentId": "attraction#afternoon",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 2,
                        "title": "오후 장소",
                        "isSeed": False,
                        "theme": "역사·전통",
                    },
                ],
            },
        },
    )

    edit_ops = output["intent"]["modify_intent"]["edit_ops"]
    assert [operation["op_id"] for operation in edit_ops] == ["op-1", "op-2"]
    assert [operation["target"]["item_id"] for operation in edit_ops] == [
        "item-1",
        "item-2",
    ]
    assert [operation["condition"]["replacement_query"] for operation in edit_ops] == [
        "조용하고 한적한 숲길을 천천히 걸을 수 있는 자연 산책 장소.",
        "차분하게 머물며 작품과 전시를 감상할 수 있는 실내 문화 공간.",
    ]
    assert [operation["condition"]["query_required"] for operation in edit_ops] == [
        True,
        True,
    ]


def test_intent_node_distinguishes_replace_without_search_query() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오후 장소만 다른 곳으로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-2",
                        "contentId": "attraction#afternoon",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 2,
                        "title": "오후 장소",
                        "isSeed": False,
                        "theme": "역사·전통",
                    },
                ],
            },
        },
    )

    condition = output["intent"]["modify_intent"]["edit_ops"][0]["condition"]
    assert condition["replacement_query"] is None
    assert condition["replacement_query_raw"] is None
    assert condition["query_required"] is False


def test_intent_node_extracts_query_after_title_without_negative_marker() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 오전 오전 장소를 조용한 숲길로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#morning",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "오전 장소",
                        "isSeed": False,
                        "theme": "바다·해안",
                    },
                ],
            },
        },
    )

    condition = output["intent"]["modify_intent"]["edit_ops"][0]["condition"]
    assert condition["replacement_query_raw"] == "조용한 숲길"
    assert condition["replacement_query"] == "조용하고 한적한 숲길을 천천히 걸을 수 있는 자연 산책 장소."
    assert condition["query_required"] is True
