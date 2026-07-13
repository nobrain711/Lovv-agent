from __future__ import annotations

from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_response_packager_node_backfills_modify_city_change_destination_id() -> None:
    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "destinationId": "KR-51-170",
                "rawModifyQuery": "도시는 강릉으로 바꿔줘.",
            },
            "intent": {
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "city_change": {
                        "target_city_id": "KR-51-150",
                        "target_city_name": "강릉시",
                    },
                },
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 9,
                    "trip_type": "2d1n",
                    "destination_id": "KR-51-150",
                    "active_required_themes": ("바다·해안",),
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "slot": "morning",
                            "placeId": "attraction#2804197",
                            "title": "아르떼뮤지엄 강릉",
                            "city_id": "KR-51-150",
                            "city_name_ko": "강릉시",
                        },
                    ],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "강릉 중심으로 다시 구성했습니다.",
                    "external_links": {},
                    "confidence": 0.5,
                    "user_notice": (),
                    "validation_result": {"planner_status_gate": "ok"},
                },
            },
        },
    )

    destination = result["response"]["response_payload"]["destination"]
    assert destination["destinationId"] == "KR-51-150"
    assert destination["name"] == "강릉시"


def test_response_packager_prefers_request_destination_for_slot_replace() -> None:
    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "requestId": "REQ-SLOT",
                "destinationId": "KR-47-130",
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "trip_type": "2d1n",
                    "destination_id": "KR-47-770",
                    "active_required_themes": ("역사·전통",),
                },
            },
            "city_select": {
                "city_selection_result": {
                    "selected_city": {
                        "city_id": "KR-47-770",
                        "city_name_ko": "영덕군",
                        "country": "KR",
                    },
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "slot": "morning",
                            "placeId": "attraction#128676",
                            "title": "경주 교촌마을",
                            "city_id": "KR-47-130",
                            "city_name_ko": "경주시",
                        },
                    ],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "경주 일정 일부를 수정했습니다.",
                    "external_links": {},
                    "confidence": 0.5,
                    "user_notice": (),
                    "validation_result": {"planner_status_gate": "ok"},
                },
            },
        },
    )

    destination = result["response"]["response_payload"]["destination"]
    assert destination["destinationId"] == "KR-47-130"
    assert destination["name"] == "경주시"
