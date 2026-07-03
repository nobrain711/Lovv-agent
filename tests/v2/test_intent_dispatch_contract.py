from __future__ import annotations

from lovv_agent_v2.agents.intent.node import intent_node


def test_intent_node_marks_create_output_with_discriminator() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "create",
                "country": "KR",
                "travel_month": 8,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "include_festivals": False,
                "raw_query": "조용한 바다 여행을 추천해줘",
            },
        },
    )

    intent = output["intent"]
    assert intent["intent_type"] == "create"
    assert intent["city_select_input"]["active_required_themes"] == ["바다·해안"]
    assert intent["preferred_theme_ids"] == ("sea_coast",)


def test_intent_node_resolves_button_clarification_from_pending_memory() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "clarify",
                "threadId": "thread-001",
                "selectedOptionId": "continue_without_festival",
            },
            "memory": {
                "pending_clarification": {
                    "reason_code": "festival_none",
                    "prompt": "축제 없이 계속할까요?",
                    "options": [
                        {
                            "option_id": "continue_without_festival",
                            "label": "축제 없이 계속",
                            "apply": {"include_festivals": False},
                            "then": "rerun_discovery",
                        },
                    ],
                },
            },
        },
    )

    intent = output["intent"]
    assert intent == {
        "intent_type": "clarify",
        "status": "resolved",
        "thread_id": "thread-001",
        "selected_option_id": "continue_without_festival",
        "resume": {"option_id": "continue_without_festival"},
        "audit": {"matched_label": "축제 없이 계속"},
    }


def test_intent_node_resolves_weather_alternative_clarification_option() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "clarify",
                "threadId": "thread-weather",
                "optionId": "generate_weather_alternative",
            },
            "response": {
                "clarification": {
                    "reason_code": "weather_alternative_available",
                    "prompt": "평년 기준 날씨 리스크가 높아 대체 일정을 만들까요?",
                    "options": [
                        {
                            "option_id": "generate_weather_alternative",
                            "label": "날씨 고려 대체 일정 생성",
                            "apply": {},
                            "then": "weather_alternative",
                        },
                    ],
                },
            },
        },
    )

    intent = output["intent"]
    assert intent["status"] == "resolved"
    assert intent["selected_option_id"] == "generate_weather_alternative"
    assert intent["resume"] == {"option_id": "generate_weather_alternative"}
    assert intent["audit"] == {"matched_label": "날씨 고려 대체 일정 생성"}


def test_intent_node_returns_clarify_unresolved_for_unknown_option() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "clarify",
                "threadId": "thread-001",
                "selectedOptionId": "missing",
            },
            "memory": {
                "pending_clarification": {
                    "reason_code": "festival_none",
                    "prompt": "축제 없이 계속할까요?",
                    "options": [
                        {
                            "option_id": "continue_without_festival",
                            "label": "축제 없이 계속",
                            "apply": {"include_festivals": False},
                            "then": "rerun_discovery",
                        },
                    ],
                },
            },
        },
    )

    intent = output["intent"]
    assert intent["intent_type"] == "clarify"
    assert intent["status"] == "needs_clarification"
    assert intent["reason_code"] == "clarify_option_unresolved"
    assert intent["selected_option_id"] is None


def test_intent_node_builds_slot_replace_modify_intent() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "destinationId": "KR-41-1",
                "rawModifyQuery": "1일차 오후 이이 유적 말고, 조용히 산책하기 좋은 자연 쪽으로 바꿔줘.",
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
                    {
                        "itemId": "item-2",
                        "contentId": "attraction#127691",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 2,
                        "title": "이이 유적",
                        "isSeed": False,
                        "theme": "역사·전통",
                    },
                ],
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "ok"
    assert modify_intent["kind"] == "slot_replace"
    assert modify_intent["destination_id"] == "KR-41-1"
    assert modify_intent["routing_hint"] == "planner_apply_edit"
    assert modify_intent["edit_ops"][0]["target"] == {
        "item_id": "item-2",
        "content_id": "attraction#127691",
        "item_type": "attraction",
        "day": 1,
        "order": 2,
        "target_text": "이이 유적",
        "resolution": "exact",
    }
    assert (
        modify_intent["edit_ops"][0]["condition"]["replacement_query"]
        == "조용하고 한적한 숲길을 천천히 걸을 수 있는 자연 산책 장소."
    )
    assert (
        modify_intent["edit_ops"][0]["condition"]["replacement_query_raw"]
        == "조용히 산책하기 좋은 자연"
    )
    assert modify_intent["edit_ops"][0]["condition"]["query_required"] is True
    assert modify_intent["edit_ops"][0]["condition"]["theme"] == "자연·트레킹"
    assert modify_intent["edit_ops"][0]["seed_policy"] == {
        "target_is_seed": False,
        "policy": "not_seed",
    }


def test_intent_node_builds_city_change_modify_intent() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "도시는 경주로 바꿔줘.",
                "currentOrder": [
                    {
                        "itemId": "item-1",
                        "contentId": "attraction#old",
                        "itemType": "attraction",
                        "day": 1,
                        "order": 1,
                        "title": "기존 장소",
                        "cityId": "KR-51-150",
                    },
                ],
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "ok"
    assert modify_intent["kind"] == "city_change"
    assert modify_intent["edit_ops"] == []
    assert modify_intent["city_change"]["target_city_id"] == "KR-47-130"
    assert modify_intent["city_change"]["target_city_name"] == "경주시"
    assert modify_intent["city_change"]["avoid_city_ids"] == ["KR-51-150"]
    assert modify_intent["routing_hint"] == "planner_direct_anchor"


def test_intent_node_builds_confirm_intent_output() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "confirm",
                "threadId": "thread-001",
                "recommendationId": "rec-001",
                "itineraryRevision": "rev-001",
            },
        },
    )

    assert output["intent"] == {
        "intent_type": "confirm",
        "status": "ok",
        "thread_id": "thread-001",
        "recommendation_id": "rec-001",
        "itinerary_revision": "rev-001",
    }
