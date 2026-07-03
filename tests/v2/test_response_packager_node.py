from __future__ import annotations

from lovv_agent_v2.agents.response_packager.agent import ResponsePackagerAgent
from lovv_agent_v2.agents.response_packager.contracts import ResponsePackagerInput
from lovv_agent_v2.agents.response_packager.packager import package_recommendation_response
from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_response_packager_flattens_verified_festival_city_payloads() -> None:
    result = response_packager_node(
        {
            "request": {
                "request_id": "REQ-FEST",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "2d1n",
                "destination_id": None,
                "themes": ("역사·전통",),
            },
            "festival_gate": {
                "result": {
                    "verified_festival_cities": [
                        {
                            "city_id": "KR-36-4",
                            "city_name": "김해시",
                            "festivals": [
                                {
                                    "festival_id": "F-1",
                                    "name": "가야문화축제",
                                    "date_status": "confirmed",
                                    "event_start_date": "2026-10",
                                    "event_end_date": "2026-10",
                                    "source": "dynamodb",
                                },
                            ],
                        },
                    ],
                },
            },
        },
    )

    payload = result["response"]["response_payload"]
    verifications = payload["festivalDateVerifications"]
    assert verifications[0]["festivalId"] == "F-1"
    assert verifications[0]["dateStatus"] == "confirmed"


def test_response_packager_agent_packages_without_unified_state() -> None:
    output = ResponsePackagerAgent().run(
        ResponsePackagerInput(
            request={
                "request_id": "REQ-AGENT",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "daytrip",
                "destination_id": None,
                "themes": ("바다·해안",),
            },
            planner_output=None,
            selected_city=None,
            festival_verifications=(),
            unsupported_conditions=(),
            clarification=None,
        ),
    )

    assert output.response["response_status"] == "modification_pending"
    assert output.response["response_payload"]["recommendationId"] == "REQ-AGENT"


def test_response_packager_uses_planner_city_name_for_direct_anchor() -> None:
    output = ResponsePackagerAgent().run(
        ResponsePackagerInput(
            request={
                "request_id": "REQ-ANCHOR",
                "country": "KR",
                "travel_month": 9,
                "trip_type": "daytrip",
                "destination_id": "KR-51-150",
                "themes": ("예술·감성",),
            },
            planner_output={
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
                "itinerary_flow_reason": "강릉 문화 공간을 하루에 묶은 일정입니다.",
                "external_links": {},
                "confidence": 0.5,
                "user_notice": (),
                "validation_result": {"planner_status_gate": "ok"},
            },
            selected_city=None,
            festival_verifications=(),
            unsupported_conditions=(),
            clarification=None,
        ),
    )

    destination = output.response["response_payload"]["destination"]
    assert destination["destinationId"] == "KR-51-150"
    assert destination["name"] == "강릉시"


def test_response_packager_agent_packages_clarification_mapping() -> None:
    clarification = {
        "reason_code": "festival_none",
        "prompt": "확정 축제 도시가 없습니다. 축제 없이 계속할까요?",
        "options": [
            {
                "option_id": "continue_without_festival",
                "label": "축제 없이 계속",
                "apply": {"include_festivals": False},
                "then": "rerun_discovery",
            },
        ],
        "context": {"travel_month": 10},
        "failure_signals": ["no_confirmed_festival_city"],
    }

    output = ResponsePackagerAgent().run(
        ResponsePackagerInput(
            request={
                "request_id": "REQ-WAIT",
                "country": "KR",
                "travel_month": 10,
                "trip_type": "daytrip",
                "destination_id": None,
                "themes": ("축제·이벤트",),
            },
            planner_output=None,
            selected_city=None,
            festival_verifications=(),
            unsupported_conditions=(),
            clarification=clarification,
        ),
    )

    payload = output.response["response_payload"]
    assert output.response["response_status"] == "END_WAIT_USER"
    assert payload["clarification"]["reasonCode"] == "festival_none"
    assert payload["explainability"]["userNotice"] == clarification["prompt"]


def test_response_packager_node_packages_modify_clarification(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {"selectedOptionId": "revise_modify_query"},
    )

    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "핵심 장소를 자연 쪽으로 바꿔줘.",
            },
            "intent": {
                "intent_type": "modification",
                "modify_intent": {
                    "status": "needs_clarification",
                    "clarification": {
                        "reason_code": "modify_seed_theme_conflict",
                        "prompt": "핵심 장소는 같은 테마 안에서만 바꿀 수 있습니다.",
                        "options": [],
                    },
                },
            },
        },
    )

    response = result["response"]
    payload = response["response_payload"]
    assert response["response_status"] == "END_WAIT_USER"
    assert payload["clarification"]["reasonCode"] == "modify_seed_theme_conflict"
    assert payload["explainability"]["userNotice"] == (
        "핵심 장소는 같은 테마 안에서만 바꿀 수 있습니다."
    )


def test_response_packager_node_packages_modify_unsupported_notice() -> None:
    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "3박 4일로 늘려줘.",
            },
            "intent": {
                "intent_type": "modification",
                "modify_intent": {
                    "status": "unsupported",
                    "unsupported_reasons": ["trip_length_change"],
                },
            },
        },
    )

    payload = result["response"]["response_payload"]
    assert result["response"]["response_status"] == "modification_pending"
    assert payload["explainability"]["unsupportedConditions"] == ("trip_length_change",)
    assert "trip_length_change" in payload["explainability"]["userNotice"]


def test_response_packager_adds_notice_for_generation_unsupported_conditions() -> None:
    response = package_recommendation_response(
        planner_output={
            "itinerary": [],
            "recommendation_reasons": (),
            "itinerary_flow_reason": "요청 조건을 반영한 일정입니다.",
            "external_links": {},
            "confidence": 0.5,
            "user_notice": (),
            "validation_result": {"planner_status_gate": "ok"},
        },
        request={
            "request_id": "REQ-UNSUPPORTED",
            "country": "KR",
            "travel_month": 10,
            "trip_type": "daytrip",
            "destination_id": None,
            "themes": ("바다·해안",),
        },
        selected_city=None,
        unsupported_conditions=("실시간 혼잡도 보장",),
    )

    assert response["explainability"]["unsupportedConditions"] == ("실시간 혼잡도 보장",)
    assert "실시간 혼잡도 보장" in response["explainability"]["userNotice"]
