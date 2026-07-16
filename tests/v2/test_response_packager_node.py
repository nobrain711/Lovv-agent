from __future__ import annotations

from lovv_agent_v2.agents.response_packager.agent import ResponsePackagerAgent
from lovv_agent_v2.agents.response_packager.clarification_resume import response_resume_update
from lovv_agent_v2.agents.planner.state.context import planner_input
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
                "helper_text": "축제 조건을 제외하고 여행지를 다시 찾습니다.",
                "apply": {"include_festivals": False}, "then": "rerun_discovery",
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
    assert payload["clarification"]["options"][0]["helperText"] == "축제 조건을 제외하고 여행지를 다시 찾습니다."
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
    assert payload["clarification"]["options"][0]["label"] == "수정 요청 다시 입력"
    assert payload["clarification"]["options"][0]["helperText"] == "수정할 일자나 순서를 포함해 다시 요청합니다."
    assert payload["explainability"]["userNotice"] == (
        "핵심 장소는 같은 테마 안에서만 바꿀 수 있습니다."
    )
    assert response["clarification_resume"]["then"] == "abort"


def test_response_packager_node_skips_interrupt_when_runtime_disables_it(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: (_ for _ in ()).throw(AssertionError("interrupt should not run")),
    )

    result = response_packager_node(
        {
            "runtime": {"interrupts_enabled": False},
            "request": {
                "request_id": "REQ-MOD-NO-INTERRUPT",
                "entryType": "modify",
                "rawModifyQuery": "두 번째 장소 바꿔줘.",
            },
            "planner": {
                "modify_context": {
                    "failed_edit": {
                        "reason_code": "slot_replace_no_candidate",
                        "target": {"day": 1, "order": 2},
                    },
                },
            },
        },
    )

    response = result["response"]
    assert response["response_status"] == "END_WAIT_USER"
    assert response["response_payload"]["recommendationId"] == "REQ-MOD-NO-INTERRUPT"
    assert "clarification_resume" not in response


def test_response_packager_node_uses_resource_text_for_failed_slot_replace(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {"selectedOptionId": "keep_current_place"},
    )

    result = response_packager_node(
        {
            "request": {"entryType": "modify", "rawModifyQuery": "두 번째 장소 바꿔줘."},
            "planner": {
                "modify_context": {
                    "failed_edit": {
                        "reason_code": "slot_replace_route_infeasible",
                        "target": {"day": 1, "order": 2},
                    },
                },
            },
        },
    )

    payload = result["response"]["response_payload"]
    assert payload["clarification"]["prompt"] == "대체 장소는 찾았지만 이동 시간이 맞지 않습니다. 조건을 조금 넓혀볼까요?"
    assert payload["clarification"]["options"][0]["then"] == "retry_slot_replace"
    assert payload["clarification"]["options"][1]["label"] == "현재 장소 유지"


def test_response_resume_broadens_failed_slot_replace_for_retry() -> None:
    result = response_resume_update(
        {
            "intent": {
                "intent_type": "modification",
                "modify_intent": {
                    "status": "ok",
                    "kind": "slot_replace",
                    "routing_hint": "planner_apply_edit",
                    "edit_ops": [
                        {
                            "op_id": "op-1",
                            "op": "replace",
                            "target": {"day": 1, "order": 2},
                            "condition": {
                                "replacement_query": "조용한 바다",
                                "theme": "바다·해안",
                            },
                            "seed_policy": {
                                "policy": "same_theme_required",
                                "required_theme": "바다·해안",
                            },
                        },
                    ],
                },
            },
            "planner": {
                "planner_output": {"itinerary": []},
                "modify_context": {
                    "failed_edit": {
                        "reason_code": "slot_replace_route_infeasible",
                        "target": {"day": 1, "order": 2},
                    },
                    "failed_edits": [{"reason_code": "slot_replace_route_infeasible"}],
                },
            },
        },
        {
            "response_payload": {
                "clarification": {
                    "reasonCode": "slot_replace_route_infeasible",
                    "options": [
                        {
                            "optionId": "broaden_replace_theme",
                            "label": "조건 완화해서 다시 찾기",
                            "apply": {},
                            "then": "retry_slot_replace",
                        },
                    ],
                },
            },
        },
        {"selectedOptionId": "broaden_replace_theme"},
    )

    edit_op = result["intent"]["modify_intent"]["edit_ops"][0]
    assert "theme" not in edit_op["condition"]
    assert edit_op["condition"]["theme_relaxed"] is True
    assert edit_op["seed_policy"]["policy"] == "theme_relaxed"
    assert "failed_edit" not in result["planner"]["modify_context"]
    assert result["response"] == {}


def test_response_resume_anchor_uses_patched_city_input_over_stale_trip_intent() -> None:
    response = {
        "response_payload": {
            "clarification": {
                "reasonCode": "anchor_festival_conflict",
                "options": [
                    {
                        "optionId": "continue_without_festival_in_anchor",
                        "label": "이 도시에서 축제 없이 계속",
                        "apply": {
                            "includeFestivals": False,
                            "destinationId": "KR-34-5",
                        },
                        "then": "anchor",
                    },
                ],
            },
        },
    }
    state = {
        "intent": {
            "trip_intent": {
                "destination_id": "KR-34-5",
                "include_festivals": True,
            },
            "city_select_input": {
                "country": "KR",
                "travel_month": 7,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "include_festivals": True,
                "cleaned_raw_query": "보령 축제 해안 여행",
                "soft_preference_query": "",
                "destination_id": "KR-34-5",
                "execution_mode": "anchored_place_search",
            },
        },
        "response": response,
    }

    result = response_resume_update(
        state,
        response,
        {"selectedOptionId": "continue_without_festival_in_anchor"},
    )

    assert "trip_intent" not in result["intent"]
    planner_request = planner_input(result)
    assert planner_request["city_id"] == "KR-34-5"
    assert planner_request["selected_city"]["selection_source"] == "direct_anchor_without_city_select"


def test_response_packager_node_resumes_with_checkpoint_option(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {
            "optionId": "continue_without_festival",
            "apply": {"includeFestivals": True},
        },
    )

    result = response_packager_node(
        {
            "request": {
                "request_id": "REQ-FEST",
                "country": "KR",
                "travel_month": 10,
                "travel_year": 2026,
                "trip_type": "daytrip",
                "include_festivals": True,
                "themes": ("바다·해안",),
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "daytrip",
                    "active_required_themes": ["바다·해안"],
                    "include_festivals": True,
                    "cleaned_raw_query": "10월 바다 축제",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                    "destination_id": None,
                    "execution_mode": "city_discovery",
                },
            },
            "festival_gate": {
                "clarification": {
                    "reason_code": "festival_none",
                    "prompt": "확정 축제 도시가 없습니다. 축제 없이 계속할까요?",
                    "options": [
                        {
                            "option_id": "continue_without_festival",
                            "label": "축제 없이 계속",
                            "helper_text": "축제 조건을 제외하고 여행지를 다시 찾습니다.",
                            "apply": {"include_festivals": False},
                            "then": "rerun_discovery",
                        },
                    ],
                },
            },
        },
    )

    city_input = result["intent"]["city_select_input"]
    assert city_input["include_festivals"] is False
    assert result["festival_gate"] == {}
    assert result["response"] == {}


def test_response_packager_node_clarifies_generation_insufficient_candidates(monkeypatch) -> None:
    captured_payloads = []

    def choose_other_city(payload):
        captured_payloads.append(payload)
        return {"selectedOptionId": "search_other_city"}

    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        choose_other_city,
    )

    result = response_packager_node(
        {
            "request": {
                "request_id": "REQ-GEN-THIN",
                "country": "KR",
                "travel_month": 8,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "themes": ("온천·휴양",),
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 8,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ["온천·휴양"],
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 휴양 여행",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                    "execution_mode": "city_discovery",
                },
            },
            "city_select": {
                "city_selection_result": {
                    "selected_city": {
                        "city_id": "KR-TEST-1",
                        "city_name_ko": "테스트시",
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
                            "placeId": "attraction#thin",
                            "title": "얇은 후보",
                        },
                    ],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "후보가 부족합니다.",
                    "external_links": {},
                    "confidence": 0.2,
                    "user_notice": ("조건에 맞는 후보가 부족합니다.",),
                    "validation_result": {
                        "planner_status_gate": "insufficient_candidates",
                    },
                },
            },
        },
    )

    clarification = captured_payloads[0]["clarification"]
    assert clarification["reasonCode"] == "generation_insufficient_candidates"
    assert [option["optionId"] for option in clarification["options"]] == [
        "relax_generation_themes",
        "search_other_city",
    ]
    city_input = result["intent"]["city_select_input"]
    assert city_input["destination_id"] is None
    assert city_input["disliked_city_ids"] == ("KR-TEST-1",)
    assert result["planner"] == {}
    assert result["response"] == {}


def test_response_resume_relaxes_generation_required_themes() -> None:
    result = response_resume_update(
        {
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 8,
                    "travel_year": 2026,
                    "trip_type": "2d1n",
                    "active_required_themes": ["온천·휴양"],
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 휴양 여행",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                    "execution_mode": "city_discovery",
                },
            },
        },
        {
            "response_payload": {
                "clarification": {
                    "reasonCode": "generation_insufficient_candidates",
                    "options": [
                            {
                                "optionId": "relax_generation_themes",
                                "label": "테마 완화",
                                "apply": {
                                    "activeRequiredThemes": [
                                        "바다·해안",
                                        "자연·트레킹",
                                        "역사·전통",
                                        "예술·감성",
                                        "온천·휴양",
                                    ],
                                },
                                "then": "rerun_discovery",
                            },
                    ],
                },
            },
        },
        {"selectedOptionId": "relax_generation_themes"},
    )

    assert "자연·트레킹" in result["intent"]["city_select_input"]["active_required_themes"]
    assert "미식·노포" not in result["intent"]["city_select_input"]["active_required_themes"]
    assert result["city_select"] == {}
    assert result["planner"] == {}


def test_response_packager_node_clarifies_weather_alternative_available(monkeypatch) -> None:
    captured_payloads = []

    def keep_primary(payload):
        captured_payloads.append(payload)
        return {"selectedOptionId": "keep_primary_itinerary"}

    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        keep_primary,
    )

    response_packager_node(
        {
            "request": {
                "request_id": "REQ-WEATHER",
                "country": "KR",
                "travel_month": 7,
                "trip_type": "2d1n",
                "themes": ("바다·해안",),
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 7,
                    "trip_type": "2d1n",
                    "active_required_themes": ["바다·해안"],
                    "include_festivals": False,
                    "execution_mode": "anchored_place_search",
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "slot": "morning",
                            "placeId": "attraction#outdoor",
                            "title": "해변 산책",
                            "city_id": "KR-51-170",
                            "city_name_ko": "동해시",
                            "indoor_outdoor": "outdoor",
                        },
                    ],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "해안 중심 일정입니다.",
                    "external_links": {},
                    "confidence": 0.7,
                    "user_notice": (),
                    "validation_result": {
                        "planner_status_gate": "ok",
                        "weather_audit": {
                            "status": "alternative_available",
                            "notice_level": "strong",
                            "risk_dimensions": {"rain": "high"},
                            "weather_sensitive_ratio": 1.0,
                        },
                    },
                },
            },
        },
    )

    clarification = captured_payloads[0]["clarification"]
    assert clarification["reasonCode"] == "weather_alternative_available"
    assert [option["optionId"] for option in clarification["options"]] == [
        "use_weather_alternative",
        "keep_primary_itinerary",
    ]


def test_response_resume_weather_alternative_uses_indoor_reserve() -> None:
    result = response_resume_update(
        {
            "request": {
                "request_id": "REQ-WEATHER",
                "country": "KR",
                "travel_month": 7,
                "trip_type": "2d1n",
                "themes": ("바다·해안",),
            },
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 7,
                    "trip_type": "2d1n",
                    "destination_id": "KR-51-170",
                    "active_required_themes": ["바다·해안"],
                    "include_festivals": False,
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        {
                            "day": 1,
                            "slot": "morning",
                            "placeId": "attraction#outdoor",
                            "title": "해변 산책",
                            "city_id": "KR-51-170",
                            "city_name_ko": "동해시",
                            "indoor_outdoor": "outdoor",
                        },
                    ],
                    "recommendation_reasons": (),
                    "itinerary_flow_reason": "해안 중심 일정입니다.",
                    "external_links": {},
                    "confidence": 0.7,
                    "user_notice": (),
                    "validation_result": {
                        "planner_status_gate": "ok",
                        "weather_audit": {"status": "alternative_available"},
                    },
                },
                "modify_context": {
                    "reserve_pool": [
                        {
                            "place_id": "attraction#indoor",
                            "title": "실내 전시관",
                            "city_id": "KR-51-170",
                            "city_name_ko": "동해시",
                            "theme_tags": ["예술·감성"],
                            "indoor_outdoor": "indoor",
                            "latitude": 37.5,
                            "longitude": 129.1,
                        },
                    ],
                },
            },
        },
        {
            "response_payload": {
                "clarification": {
                    "reasonCode": "weather_alternative_available",
                    "options": [
                        {
                            "optionId": "use_weather_alternative",
                            "label": "날씨 대체 일정 보기",
                            "apply": {},
                            "then": "weather_alternative",
                        },
                    ],
                },
            },
        },
        {"selectedOptionId": "use_weather_alternative"},
    )

    payload = result["response"]["response_payload"]
    item = payload["itinerary"]["days"][0]["items"][0]
    assert item["title"] == "실내 전시관"
    assert item["indoorOutdoor"] == "indoor"
    assert "clarification" not in payload
    assert result["response"]["clarification_resume"]["option_id"] == "use_weather_alternative"


def test_response_resume_update_restarts_from_corrected_clarify_payload() -> None:
    result = response_resume_update(
        {
            "intent": {
                "clarification": {"reason_code": "contradiction"},
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 8,
                    "travel_year": 2026,
                    "trip_type": "daytrip",
                    "active_required_themes": ["바다·해안"],
                    "include_festivals": False,
                    "cleaned_raw_query": "속초는 싫은데 속초 바다 여행지를 추천해줘",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                },
            },
            "response": {"response_payload": {"clarification": {"reasonCode": "contradiction"}}},
        },
        {
            "response_payload": {
                "clarification": {
                    "reasonCode": "contradiction",
                    "options": [{"optionId": "revise_conditions"}],
                },
            },
        },
        {
            "entryType": "clarify",
            "country": "KR",
            "travelMonth": 8,
            "travelYear": 2026,
            "tripType": "daytrip",
            "themes": ["바다·해안"],
            "includeFestivals": False,
            "naturalLanguageQuery": "강릉 바다 당일 여행지를 추천해줘.",
        },
    )

    intent = result["intent"]
    assert intent["intent_type"] == "create"
    assert intent["city_select_input"]["cleaned_raw_query"] == "강릉 바다 당일 여행지를 추천해줘"
    assert intent["city_select_input"]["preferred_region_ids"] == ("KR-51-150",)
    assert result["response"] == {}
    assert result["planner"] == {}


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


def test_response_packager_exposes_optional_alternative_itinerary() -> None:
    response = package_recommendation_response(
        planner_output={
            "itinerary": [],
            "recommendation_reasons": (),
            "itinerary_flow_reason": "요청 조건을 반영한 일정입니다.",
            "external_links": {},
            "confidence": 0.5,
            "user_notice": (),
            "validation_result": {"planner_status_gate": "ok"},
            "alternative_itinerary": (
                {
                    "day": 1,
                    "slot": "morning",
                    "placeId": "p-alt",
                    "title": "실내 전시관",
                    "city_id": "KR-TEST",
                    "indoor_outdoor": "indoor",
                },
            ),
        },
        request={
            "request_id": "REQ-WEATHER",
            "country": "KR",
            "travel_month": 7,
            "trip_type": "daytrip",
            "destination_id": None,
            "themes": ("예술·감성",),
        },
        selected_city=None,
    )

    item = response["alternativeItinerary"]["days"][0]["items"][0]
    assert item["contentId"] == "p-alt"
    assert item["indoorOutdoor"] == "indoor"
