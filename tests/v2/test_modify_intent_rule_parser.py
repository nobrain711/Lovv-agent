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


def test_intent_node_generalizes_freeform_replacement_query_to_hyde_sentence() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 2번째 장소를 사진 찍기 좋은 레트로 골목으로 바꿔줘.",
                "currentOrder": [
                    _current_item("item-1", "attraction#one", 1),
                    _current_item("item-2", "attraction#two", 2),
                ],
            },
        },
    )

    condition = output["intent"]["modify_intent"]["edit_ops"][0]["condition"]
    assert condition["replacement_query_raw"] == "사진 찍기 좋은 레트로 골목"
    assert condition["replacement_query"] == (
        "사진 찍기 좋은 레트로 골목 분위기와 장소 유형이 잘 드러나는 방문지."
    )
    assert condition["query_required"] is True


def test_intent_node_supports_korean_ordinal_slot_replace() -> None:
    for phrase, expected_order in (
        ("첫 번째", 1),
        ("두 번째", 2),
        ("세 번째", 3),
        ("네 번째", 4),
        ("마지막", 4),
    ):
        output = intent_node(
            {
                "request": {
                    "entryType": "modify",
                    "threadId": "thread-001",
                    "itineraryRevision": "rev-001",
                    "rawModifyQuery": f"1일차 {phrase} 장소를 실내 전시 공간으로 바꿔줘.",
                    "currentOrder": [
                        _current_item("item-1", "attraction#one", 1),
                        _current_item("item-2", "attraction#two", 2),
                        _current_item("item-3", "attraction#three", 3),
                        _current_item("item-4", "attraction#four", 4),
                    ],
                },
            },
        )

        operation = output["intent"]["modify_intent"]["edit_ops"][0]
        assert operation["target"]["item_id"] == f"item-{expected_order}"
        assert operation["target"]["order"] == expected_order


def test_intent_node_supports_multiple_targets_in_same_day_with_shared_query() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 2번째, 3번째 장소를 실내 전시 공간으로 바꿔줘.",
                "currentOrder": [
                    _current_item("item-1", "attraction#one", 1),
                    _current_item("item-2", "attraction#two", 2),
                    _current_item("item-3", "attraction#three", 3),
                ],
            },
        },
    )

    edit_ops = output["intent"]["modify_intent"]["edit_ops"]
    assert [operation["target"]["item_id"] for operation in edit_ops] == ["item-2", "item-3"]
    assert [operation["condition"]["replacement_query_raw"] for operation in edit_ops] == [
        "실내 전시 공간",
        "실내 전시 공간",
    ]


def test_intent_node_builds_day_regenerate_modify_intent() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "1일차 전체를 바다 산책 느낌으로 바꿔줘.",
                "currentOrder": [
                    _current_item("item-1", "attraction#one", 1),
                    _current_item("item-2", "attraction#two", 2),
                ],
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "ok"
    assert modify_intent["kind"] == "day_regenerate"
    assert modify_intent["routing_hint"] == "planner_apply_edit"
    assert modify_intent["day_regenerate"]["day"] == 1
    assert modify_intent["day_regenerate"]["condition"]["replacement_query_raw"] == "바다 산책 느낌"


def test_intent_node_builds_day_regenerate_from_loose_day_phrases() -> None:
    for raw_query, expected_day, expected_query in (
        ("첫날 코스 통째로 바다 산책 느낌으로 바꿔줘.", 1, "바다 산책 느낌"),
        ("둘째 날 일정 다 조용한 숲길로 갈아엎어줘.", 2, "조용한 숲길"),
        ("마지막 날 전부 실내 전시 공간으로 교체해줘.", 2, "실내 전시 공간"),
    ):
        output = intent_node(
            {
                "request": {
                    "entryType": "modify",
                    "threadId": "thread-001",
                    "itineraryRevision": "rev-001",
                    "rawModifyQuery": raw_query,
                    "currentOrder": [
                        _current_item("item-1", "attraction#one", 1, day=1),
                        _current_item("item-2", "attraction#two", 2, day=1),
                        _current_item("item-3", "attraction#three", 1, day=2),
                    ],
                },
            },
        )

        modify_intent = output["intent"]["modify_intent"]
        assert modify_intent["status"] == "ok"
        assert modify_intent["kind"] == "day_regenerate"
        assert modify_intent["day_regenerate"]["day"] == expected_day
        assert modify_intent["day_regenerate"]["condition"]["replacement_query_raw"] == expected_query


def _current_item(
    item_id: str,
    content_id: str,
    order: int,
    *,
    day: int = 1,
) -> dict[str, object]:
    return {
        "itemId": item_id,
        "contentId": content_id,
        "itemType": "attraction",
        "day": day,
        "order": order,
        "title": f"{order}번째 장소",
        "isSeed": False,
        "theme": "역사·전통",
    }
