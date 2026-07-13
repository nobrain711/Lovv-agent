from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_deduplicates_replacement_notice() -> None:
    result = apply_edit_node(
        {
            "request": {"request_id": "REQ-EDIT", "currentOrder": [_item()]},
            "intent": {
                "city_select_input": {"destination_id": "KR-47-130"},
                "modify_intent": {
                    "status": "ok",
                    "kind": "slot_replace",
                    "routing_hint": "planner_apply_edit",
                    "edit_ops": [
                        {
                            "op_id": "op-1",
                            "op": "REPLACE",
                            "target": {"content_id": "attraction#old", "day": 1, "order": 1},
                            "condition": {"replacement_query": None, "avoid_content_ids": []},
                            "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
                        },
                    ],
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [_planner_item()],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "기존 일정입니다.",
                    "external_links": {},
                    "confidence": 0.76,
                    "user_notice": ("요청한 장소를 같은 일정 안에서 대체했습니다.",),
                    "validation_result": {"planner_status_gate": "ok"},
                    "alternative_itinerary": (),
                },
                "modify_context": {"reserve_pool": [_candidate()]},
            },
        },
    )

    assert result["planner"]["planner_output"]["user_notice"] == (
        "요청한 장소를 같은 일정 안에서 대체했습니다.",
    )


def test_apply_edit_deduplicates_string_replacement_notice() -> None:
    result = apply_edit_node(
        {
            "request": {"request_id": "REQ-EDIT", "currentOrder": [_item()]},
            "intent": {
                "city_select_input": {"destination_id": "KR-47-130"},
                "modify_intent": {
                    "status": "ok",
                    "kind": "slot_replace",
                    "routing_hint": "planner_apply_edit",
                    "edit_ops": [
                        {
                            "op_id": "op-1",
                            "op": "REPLACE",
                            "target": {"content_id": "attraction#old", "day": 1, "order": 1},
                            "condition": {"replacement_query": None, "avoid_content_ids": []},
                            "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
                        },
                    ],
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [_planner_item()],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "기존 일정입니다.",
                    "external_links": {},
                    "confidence": 0.76,
                    "user_notice": "요청한 장소를 같은 일정 안에서 대체했습니다. 요청한 장소를 같은 일정 안에서 대체했습니다.",
                    "validation_result": {"planner_status_gate": "ok"},
                    "alternative_itinerary": (),
                },
                "modify_context": {"reserve_pool": [_candidate()]},
            },
        },
    )

    assert result["planner"]["planner_output"]["user_notice"] == (
        "요청한 장소를 같은 일정 안에서 대체했습니다.",
    )


def _item() -> dict[str, object]:
    return {
        "itemId": "item-1",
        "contentId": "attraction#old",
        "itemType": "attraction",
        "day": 1,
        "order": 1,
        "title": "기존 장소",
        "cityId": "KR-47-130",
        "theme": "역사·전통",
        "latitude": 35.83,
        "longitude": 129.21,
    }


def _planner_item() -> dict[str, object]:
    return {
        "day": 1,
        "order": 1,
        "placeId": "attraction#old",
        "title": "기존 장소",
        "latitude": 35.83,
        "longitude": 129.21,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
    }


def _candidate() -> dict[str, object]:
    return {
        "place_id": "attraction#new",
        "title": "새 장소",
        "latitude": 35.831,
        "longitude": 129.211,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "score_audit": {"score_components": {"raw_similarity": 0.8}},
    }
