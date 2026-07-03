from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.assemble_itinerary.node import assemble_itinerary_node
from lovv_agent_v2.agents.response_packager.packager import package_recommendation_response


def test_assemble_itinerary_preserves_seed_flag() -> None:
    state = {
        "planner": {
            "planner_input": {
                "min_count": 1,
                "trip_type": "daytrip",
                "active_required_themes": ("역사·전통",),
            },
            "scratch": {
                "route": {
                    "days": [
                        {
                            "day": 1,
                            "places": [
                                {
                                    "move_min_from_prev": 0,
                                    "place": {
                                        "placeId": "attraction#seed",
                                        "title": "시드 장소",
                                        "item_type": "attraction",
                                        "is_seed": True,
                                        "theme_tags": ("역사·전통",),
                                    },
                                },
                            ],
                        },
                    ],
                    "audit": {},
                },
                "selection": {"audit": {"min_count": 1}},
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-41-1",
                    "city_name_ko": "파주시",
                    "country": "KR",
                },
            },
        },
    }

    item = assemble_itinerary_node(state)["planner"]["planner_output"]["itinerary"][0]

    assert item["isSeed"] is True
    assert item["reason_code"] == "seed_floor"


def test_packager_exposes_seed_flag_for_saved_itinerary() -> None:
    response = package_recommendation_response(
        planner_output={
            "itinerary": [
                {
                    "day": 1,
                    "slot": "morning",
                    "placeId": "attraction#seed",
                    "title": "시드 장소",
                    "city_id": "KR-41-1",
                    "theme_tags": ("역사·전통",),
                    "reason_code": "seed_floor",
                },
            ],
            "recommendation_reasons": (),
            "itinerary_flow_reason": "시드 장소를 중심으로 만든 일정입니다.",
            "external_links": {},
            "confidence": 0.7,
            "user_notice": (),
            "validation_result": {"planner_status_gate": "ok"},
        },
        request={
            "request_id": "REQ-SEED",
            "country": "KR",
            "travel_month": 10,
            "trip_type": "daytrip",
            "destination_id": None,
            "themes": ("역사·전통",),
        },
        selected_city=None,
    )

    item = response["itinerary"]["days"][0]["items"][0]
    assert item["day"] == 1
    assert item["order"] == 1
    assert item["itemType"] == "attraction"
    assert item["cityId"] == "KR-41-1"
    assert item["theme"] == "역사·전통"
    assert item["isSeed"] is True
