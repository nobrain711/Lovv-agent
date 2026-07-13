from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_seed_target_does_not_fallback_to_off_theme_candidate() -> None:
    intent = _slot_replace_intent()
    edit_op = intent["modify_intent"]["edit_ops"][0]
    edit_op["seed_policy"] = {
        "target_is_seed": True,
        "policy": "same_theme_required",
        "required_theme": "역사·전통",
    }
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": intent,
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate(
                            "attraction#far-history",
                            "너무 먼 역사 장소",
                            33.45,
                            126.55,
                            theme="역사·전통",
                        ),
                        _candidate(
                            "attraction#near-food",
                            "가까운 미식 장소",
                            35.833,
                            129.219,
                            theme="미식·노포",
                        ),
                    ],
                },
            },
        },
    )

    failed = result["planner"]["modify_context"]["failed_edit"]
    assert failed["reason_code"] == "slot_replace_route_infeasible"
    assert failed["tried_candidate_count"] == 1
    assert failed["failed_route_candidate_count"] == 1


def _slot_replace_intent() -> dict[str, object]:
    return {
        "intent_type": "modification",
        "city_select_input": {
            "country": "KR",
            "travel_month": 10,
            "trip_type": "2d1n",
            "active_required_themes": ("역사·전통",),
            "destination_id": "KR-47-130",
            "include_festivals": False,
        },
        "modify_intent": {
            "status": "ok",
            "kind": "slot_replace",
            "routing_hint": "planner_apply_edit",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#old",
                        "day": 1,
                        "order": 2,
                    },
                    "condition": {
                        "replacement_query": None,
                        "theme": "역사·전통",
                        "avoid_content_ids": ["attraction#old"],
                    },
                },
            ],
        },
    }


def _request_current_order() -> dict[str, object]:
    return {
        "request_id": "REQ-EDIT",
        "country": "KR",
        "travel_month": 10,
        "trip_type": "2d1n",
        "destinationId": "KR-47-130",
        "currentOrder": [
            _order_item("item-1", "attraction#seed", "경주 교촌마을", 1, 1, 35.8296, 129.2147),
            _order_item("item-2", "attraction#old", "경주 계림", 1, 2, 35.8326, 129.2190),
            _order_item("item-3", "attraction#third", "육부전", 1, 3, 35.8170, 129.2144),
        ],
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": [
            _planner_item("attraction#seed", "경주 교촌마을", 1, 1, 35.8296, 129.2147),
            _planner_item("attraction#old", "경주 계림", 1, 2, 35.8326, 129.2190),
            _planner_item("attraction#third", "육부전", 1, 3, 35.8170, 129.2144),
        ],
        "recommendation_reasons": ("경주시 안에서 역사·전통 균형을 우선했습니다.",),
        "itinerary_flow_reason": "기존 일정입니다.",
        "external_links": {},
        "confidence": 0.76,
        "user_notice": (),
        "validation_result": {"planner_status_gate": "ok"},
        "alternative_itinerary": (),
    }


def _order_item(
    item_id: str,
    content_id: str,
    title: str,
    day: int,
    order: int,
    latitude: float,
    longitude: float,
) -> dict[str, object]:
    return {
        "itemId": item_id,
        "contentId": content_id,
        "day": day,
        "order": order,
        "title": title,
        "isSeed": item_id == "item-2",
        "cityId": "KR-47-130",
        "theme": "역사·전통",
        "latitude": latitude,
        "longitude": longitude,
    }


def _planner_item(
    place_id: str,
    title: str,
    day: int,
    order: int,
    latitude: float,
    longitude: float,
) -> dict[str, object]:
    return {
        "day": day,
        "order": order,
        "placeId": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "isSeed": place_id == "attraction#old",
    }


def _candidate(
    place_id: str,
    title: str,
    latitude: float,
    longitude: float,
    *,
    theme: str,
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": (theme,),
        "source": "reserve",
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
    }
