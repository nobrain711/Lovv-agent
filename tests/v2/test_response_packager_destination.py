from __future__ import annotations

from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_response_packager_node_backfills_modify_city_change_destination_id() -> None:
    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "rawModifyQuery": "도시는 강릉으로 바꿔줘.",
            },
            "intent": {
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
