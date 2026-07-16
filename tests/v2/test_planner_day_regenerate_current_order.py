from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node
from lovv_agent_v2.agents.planner.steps.apply_edit.current_order_snapshot import (
    merge_current_order_item,
)


def test_day_regenerate_preserves_latest_current_order_over_stale_checkpoint() -> None:
    result = apply_edit_node(
        {
            "request": {
                "request_id": "REQ-EDIT-CURRENT-ORDER",
                "destinationId": "KR-47-130",
                "currentOrder": [
                    _current_item(1, 1),
                    _current_item(1, 2),
                    _current_item(2, 1),
                    _current_item(2, 2),
                ],
            },
            "intent": {
                "modify_intent": {
                    "status": "ok",
                    "kind": "day_regenerate",
                    "routing_hint": "planner_apply_edit",
                    "day_regenerate": {
                        "day": 1,
                        "condition": {
                            "replacement_query": None,
                            "theme": None,
                            "avoid_content_ids": [],
                        },
                    },
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        _stale_planner_item(1, 1),
                        _stale_planner_item(1, 2),
                        _stale_planner_item(2, 1),
                        _stale_planner_item(2, 2),
                    ],
                    "validation_result": {"planner_status_gate": "ok"},
                },
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "새 첫 장소"),
                        _candidate("attraction#new-2", "새 둘째 장소"),
                    ],
                },
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    untouched_day = [item for item in itinerary if item["day"] == 2]
    assert [item["placeId"] for item in untouched_day] == [
        "attraction#latest-day2-1",
        "attraction#latest-day2-2",
    ]


def test_day_regenerate_preserves_request_fields_for_same_content_id() -> None:
    latest_day_two = _current_item(2, 1)
    latest_day_two["timeOfDay"] = "evening"
    stale_day_two = _stale_planner_item(2, 1)
    stale_day_two.update(
        {
            "placeId": latest_day_two["contentId"],
            "title": "checkpoint의 오래된 제목",
            "slot": "morning",
            "latitude": 33.1,
            "longitude": 126.1,
        },
    )
    result = apply_edit_node(
        {
            "request": {
                "request_id": "REQ-SAME-CONTENT-ID",
                "destinationId": "KR-47-130",
                "currentOrder": [_current_item(1, 1), latest_day_two],
            },
            "intent": {
                "modify_intent": {
                    "status": "ok",
                    "kind": "day_regenerate",
                    "routing_hint": "planner_apply_edit",
                    "day_regenerate": {
                        "day": 1,
                        "condition": {
                            "replacement_query": None,
                            "theme": None,
                            "avoid_content_ids": [],
                        },
                    },
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [_stale_planner_item(1, 1), stale_day_two],
                    "validation_result": {"planner_status_gate": "ok"},
                },
                "modify_context": {
                    "reserve_pool": [_candidate("attraction#new-1", "새 첫 장소")],
                },
            },
        },
    )

    untouched = next(
        item for item in result["planner"]["planner_output"]["itinerary"] if item["day"] == 2
    )
    assert untouched["placeId"] == latest_day_two["contentId"]
    assert untouched["title"] == latest_day_two["title"]
    assert untouched["slot"] == "evening"
    assert untouched["latitude"] == latest_day_two["latitude"]
    assert untouched["longitude"] == latest_day_two["longitude"]


def test_current_order_overlay_ignores_invalid_optional_exposure_type() -> None:
    result = merge_current_order_item(
        {"placeId": "attraction#same", "indoor_outdoor": "outdoor"},
        {"indoorOutdoor": []},
        "attraction#same",
    )

    assert result["indoor_outdoor"] == "outdoor"


def _current_item(day: int, order: int):
    return {
        "itemId": f"item-{day}-{order}",
        "contentId": f"attraction#latest-day{day}-{order}",
        "itemType": "attraction",
        "day": day,
        "order": order,
        "title": f"최신 {day}일차 {order}번째 장소",
        "isSeed": False,
        "cityId": "KR-47-130",
        "theme": "역사·전통",
        "latitude": 35.82 + (day / 100),
        "longitude": 129.21 + (order / 100),
    }


def _stale_planner_item(day: int, order: int):
    return {
        "day": day,
        "order": order,
        "placeId": f"attraction#stale-day{day}-{order}",
        "title": f"이전 {day}일차 {order}번째 장소",
        "latitude": 35.82 + (day / 100),
        "longitude": 129.21 + (order / 100),
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "isSeed": False,
    }


def _candidate(place_id: str, title: str):
    return {
        "place_id": place_id,
        "title": title,
        "latitude": 35.829,
        "longitude": 129.214,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
    }
