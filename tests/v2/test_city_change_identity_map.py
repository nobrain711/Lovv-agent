from __future__ import annotations

from lovv_agent_v2.agents.intent.modify_prompt import validate_modify_prompt_output
from lovv_agent_v2.agents.intent.node import intent_node


def test_rule_parser_resolves_city_change_from_identity_map() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "도시는 군산으로 바꿔줘.",
                "currentOrder": [_current_item()],
            },
        },
    )

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["kind"] == "city_change"
    assert modify_intent["city_change"]["target_city_id"] == "KR-37-2"
    assert modify_intent["city_change"]["target_city_name"] == "군산시"
    assert modify_intent["routing_hint"] == "planner_direct_anchor"


def test_llm_normalizer_resolves_city_change_from_identity_map() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": {"new_city": "군산"},
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_direct_anchor",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "도시는 군산으로 바꿔줘.",
            "currentOrder": [_current_item()],
        },
    )

    assert result["city_change"]["target_city_id"] == "KR-37-2"
    assert result["city_change"]["target_city_name"] == "군산시"


def test_llm_normalizer_resolves_omitted_city_from_raw_query() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": {},
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_direct_anchor",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "도시는 군산으로 바꿔줘.",
            "currentOrder": [],
        },
    )

    assert result["city_change"]["target_city_id"] == "KR-37-2"
    assert result["city_change"]["target_city_name"] == "군산시"


def test_llm_normalizer_keeps_targetless_city_change_as_rediscovery() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": {},
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "city_select_rediscovery",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "다른 도시로 바꿔줘.",
            "currentOrder": [_current_item()],
        },
    )

    assert result["routing_hint"] == "city_select_rediscovery"
    assert result["city_change"]["target_city_id"] is None
    assert result["city_change"]["target_city_name"] is None
    assert result["city_change"]["avoid_city_ids"] == ["KR-51-150"]


def test_llm_normalizer_prefers_direct_anchor_when_city_is_resolved() -> None:
    result = validate_modify_prompt_output(
        {
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": {"new_city": "군산"},
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "city_select_rediscovery",
            "audit": {"parser": "llm"},
        },
        request={
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "도시는 군산으로 바꿔줘.",
            "currentOrder": [_current_item()],
        },
    )

    assert result["routing_hint"] == "planner_direct_anchor"
    assert result["city_change"]["target_city_id"] == "KR-37-2"


def _current_item() -> dict[str, object]:
    return {
        "itemId": "item-1",
        "contentId": "attraction#old",
        "itemType": "attraction",
        "day": 1,
        "order": 1,
        "title": "기존 장소",
        "cityId": "KR-51-150",
    }
