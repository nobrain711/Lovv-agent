from __future__ import annotations

from typing import Any

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.intent.modify_prompt import validate_modify_prompt_output
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.core.state import UnifiedAgentState


def test_intent_node_uses_prompt_runtime_for_modify_intent() -> None:
    runtime = RecordingIntentRuntime(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#127691",
                        "item_type": "attraction",
                        "day": 1,
                        "order": 2,
                        "target_text": "이이 유적",
                        "resolution": "exact",
                    },
                    "condition": {
                        "replacement_query": "실내 전시 공간",
                        "theme": "예술·감성",
                        "mood": "quiet",
                        "place_type": "museum",
                        "location": None,
                        "avoid_content_ids": ["attraction#127691"],
                    },
                    "seed_policy": {
                        "target_is_seed": False,
                        "policy": "not_seed",
                    },
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
    )
    state: UnifiedAgentState = {
        "request": {
            "entryType": "modify",
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 이이 유적 말고 실내 전시 공간으로 바꿔줘.",
            "currentOrder": [
                {
                    "itemId": "item-2",
                    "contentId": "attraction#127691",
                    "itemType": "attraction",
                    "day": 1,
                    "order": 2,
                    "title": "이이 유적",
                    "isSeed": False,
                },
            ],
        },
    }

    with invocation_runtime(
        {"intent_prompt_runtime": {"runtime": runtime, "schema_retry_limit": 0}},
    ):
        output = intent_node(state)

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["intent_type"] == "modification"
    assert modify_intent["raw_modify_query"] == state["request"]["rawModifyQuery"]
    condition = modify_intent["edit_ops"][0]["condition"]
    assert condition["replacement_query"] == "차분하게 머물며 작품과 전시를 감상할 수 있는 실내 문화 공간."
    assert condition["replacement_query_raw"] == "실내 전시 공간"
    assert condition["query_required"] is True
    assert modify_intent["edit_ops"][0]["condition"]["theme"] == "예술·감성"
    assert modify_intent["audit"] == {"parser": "llm"}
    assert "Lovv V2 Modify Intent Agent" in runtime.requests[0]["system"][0]["text"]


def test_intent_node_keeps_rule_slot_replace_when_prompt_cannot_resolve_target() -> None:
    runtime = RecordingIntentRuntime(
        {
            "status": "needs_clarification",
            "kind": "slot_replace",
            "edit_ops": [],
            "city_change": None,
            "clarification": {
                "reason_code": "modify_target_unresolved",
                "prompt": "어떤 장소를 바꿀까요?",
                "options": [],
            },
            "unsupported_reasons": [],
            "routing_hint": "response_packager_wait_user",
            "audit": {"parser": "llm"},
        },
    )
    state: UnifiedAgentState = {
        "request": {
            "entryType": "modify",
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 세 번째 장소를 실내 전시 공간으로 바꿔줘.",
            "currentOrder": [
                _current_item("item-1", "attraction#one", 1),
                _current_item("item-2", "attraction#two", 2),
                _current_item("item-3", "attraction#three", 3),
            ],
        },
    }

    with invocation_runtime(
        {"intent_prompt_runtime": {"runtime": runtime, "schema_retry_limit": 0}},
    ):
        output = intent_node(state)

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["status"] == "ok"
    assert modify_intent["edit_ops"][0]["target"]["item_id"] == "item-3"
    assert modify_intent["audit"] == {"parser": "rule_v2"}


def test_intent_node_keeps_rule_multi_slot_replace_even_when_prompt_returns_single_op() -> None:
    runtime = RecordingIntentRuntime(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#two",
                        "item_type": "attraction",
                        "day": 1,
                        "order": 2,
                        "target_text": "2번째 장소",
                        "resolution": "exact",
                    },
                    "condition": {
                        "replacement_query": "실내 전시 공간",
                        "theme": "예술·감성",
                        "mood": "quiet",
                        "place_type": "museum",
                        "location": None,
                        "avoid_content_ids": ["attraction#two"],
                    },
                    "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
    )
    state: UnifiedAgentState = {
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
    }

    with invocation_runtime(
        {"intent_prompt_runtime": {"runtime": runtime, "schema_retry_limit": 0}},
    ):
        output = intent_node(state)

    modify_intent = output["intent"]["modify_intent"]
    assert [operation["target"]["item_id"] for operation in modify_intent["edit_ops"]] == [
        "item-2",
        "item-3",
    ]
    assert modify_intent["audit"] == {"parser": "rule_v2"}


def test_modify_prompt_validator_normalizes_replacement_query_to_hyde() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#127691",
                        "item_type": "attraction",
                        "day": 1,
                        "order": 2,
                        "target_text": "기존 장소",
                        "resolution": "exact",
                    },
                    "condition": {
                        "replacement_query": "실내 전시 공간",
                        "theme": "예술·감성",
                        "mood": "quiet",
                        "place_type": "museum",
                        "location": None,
                        "avoid_content_ids": ["attraction#127691"],
                    },
                    "seed_policy": {
                        "target_is_seed": False,
                        "policy": "not_seed",
                    },
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 기존 장소를 실내 전시 공간으로 바꿔줘.",
        },
    )

    condition = result["edit_ops"][0]["condition"]
    assert condition["replacement_query_raw"] == "실내 전시 공간"
    assert condition["replacement_query"] == "차분하게 머물며 작품과 전시를 감상할 수 있는 실내 문화 공간."
    assert condition["query_required"] is True


def test_modify_prompt_validator_canonicalizes_loose_slot_replace_shape() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "target_item_id": "item-1",
                    "target_day": 1,
                    "target_order": 1,
                    "new_content_description": "조용한 숲길",
                    "routing_hint": "planner_apply_edit",
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
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
    )

    operation = result["edit_ops"][0]
    assert operation["op"] == "REPLACE"
    assert operation["target"]["item_id"] == "item-1"
    assert operation["target"]["content_id"] == "attraction#morning"
    assert operation["condition"]["replacement_query_raw"] == "조용한 숲길"
    assert operation["condition"]["replacement_query"] == "조용하고 한적한 숲길을 천천히 걸을 수 있는 자연 산책 장소."
    assert operation["condition"]["query_required"] is True


def test_modify_prompt_validator_canonicalizes_nested_target_shape() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "target": {
                        "item_id": "item-1",
                        "day": 1,
                        "order": 1,
                    },
                    "replacement_query": "조용한 숲길",
                    "routing_hint": "planner_apply_edit",
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오전은 조용한 숲길로 바꿔줘.",
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
    )

    operation = result["edit_ops"][0]
    assert operation["target"]["item_id"] == "item-1"
    assert operation["target"]["content_id"] == "attraction#morning"
    assert operation["condition"]["replacement_query_raw"] == "조용한 숲길"
    assert operation["condition"]["query_required"] is True


def test_modify_prompt_validator_resolves_loose_slot_position_from_current_order() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "target": {"target_day": 1, "target_order": 2},
                    "replacement_query": "실내 전시 공간",
                },
            ],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "첫날 가운데 코스는 전시 보는 곳으로 바꿀 수 있어?",
            "currentOrder": [
                {
                    "itemId": "item-2",
                    "contentId": "attraction#252544",
                    "itemType": "attraction",
                    "day": 1,
                    "order": 2,
                    "title": "영해향교",
                    "isSeed": False,
                    "theme": "역사·전통",
                },
            ],
        },
    )

    operation = result["edit_ops"][0]
    assert operation["target"]["item_id"] == "item-2"
    assert operation["target"]["content_id"] == "attraction#252544"
    assert operation["target"]["day"] == 1
    assert operation["target"]["order"] == 2
    assert operation["condition"]["replacement_query_raw"] == "실내 전시 공간"


def test_modify_prompt_validator_canonicalizes_day_regenerate_shape() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "day_regenerate",
            "edit_ops": [],
            "day_regenerate": {
                "target_day": 2,
                "replacement_query": "바다 산책 느낌",
            },
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "둘째 날 일정은 바다 산책 느낌으로 통째로 바꿔줘.",
            "currentOrder": [
                _current_item("item-1", "attraction#one", 1),
                _current_item("item-2", "attraction#two", 2),
            ],
        },
    )

    assert result["kind"] == "day_regenerate"
    assert result["routing_hint"] == "planner_apply_edit"
    assert result["day_regenerate"]["day"] == 2
    assert result["day_regenerate"]["condition"]["replacement_query_raw"] == "바다 산책 느낌"
    assert result["day_regenerate"]["condition"]["query_required"] is True


def test_modify_prompt_validator_canonicalizes_loose_city_change_shape() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": {"new_city": "경주"},
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "city_select_rediscovery",
            "audit": {"parser": "llm"},
        },
        request={
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
    )

    assert result["city_change"] == {
        "target_city_id": "KR-47-130",
        "target_city_name": "경주시",
        "city_preference_query": "도시는 경주로 바꿔줘.",
        "carry_over_themes": True,
        "carry_over_festivals": True,
        "avoid_city_ids": ["KR-51-150"],
    }


def test_modify_prompt_validator_normalizes_seed_conflict_clarification() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "needs_clarification",
            "kind": "slot_replace",
            "edit_ops": [],
            "city_change": None,
            "clarification": {
                "reason": "seed replacement requires same theme",
                "suggestion": "please specify a same-theme replacement",
            },
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오전 핵심 유적 말고 자연 산책지로 바꿔줘.",
        },
    )

    assert result["routing_hint"] == "response_packager_wait_user"
    assert result["clarification"] == {
        "reason_code": "modify_seed_theme_conflict",
        "prompt": "please specify a same-theme replacement",
        "options": [],
    }


class RecordingIntentRuntime:
    def __init__(self, structured_output: dict[str, Any]) -> None:
        self.structured_output = structured_output
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return {"structured_output": self.structured_output}


def _current_item(item_id: str, content_id: str, order: int) -> dict[str, object]:
    return {
        "itemId": item_id,
        "contentId": content_id,
        "itemType": "attraction",
        "day": 1,
        "order": order,
        "title": f"{order}번째 장소",
        "isSeed": False,
    }
