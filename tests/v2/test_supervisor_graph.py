from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node


def test_supervisor_starts_non_intent_flow_at_profile() -> None:
    result = supervisor_node({"intent": {"intent_output": {"country": "KR"}}})

    assert result["routing"]["next_node"] == "profile"
    assert result["routing"]["completed_groups"] == []


def test_supervisor_routes_profile_to_festival_gate() -> None:
    result = supervisor_node(
        {
            "intent": {"city_select_input": {"country": "KR"}},
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "festival_verifier"
    assert result["routing"]["completed_groups"] == ["profile"]


def test_supervisor_routes_itinerary_confirmation_to_profile_before_end() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
        },
    )

    assert result["routing"]["next_node"] == "profile"
    assert result["routing"]["completed_groups"] == []


def test_supervisor_routes_confirmation_to_profile_after_pending_response() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
            "profile": {"audit": {"profile_active": False}},
            "response": {
                "response_status": "modification_pending",
                "response_payload": {"recommendationId": "REC-1"},
            },
        },
    )

    assert result["routing"]["next_node"] == "profile"
    assert result["routing"]["completed_groups"] == ["profile", "response"]


def test_supervisor_ends_after_itinerary_confirmation_profile_update() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
            },
            "profile": {
                "profile_update": {"reason": "itinerary_confirmed"},
                "audit": {"profile_update_requested": True},
            },
        },
    )

    assert result["routing"]["next_node"] == "end"
    assert result["routing"]["completed_groups"] == ["profile"]


def test_supervisor_skips_festival_gate_when_festivals_excluded() -> None:
    result = supervisor_node(
        {
            "request": {"include_festivals": False},
            "intent": {"city_select_input": {"country": "KR", "include_festivals": False}},
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "city_select"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_single_anchor_without_festival_to_planner() -> None:
    result = supervisor_node(
        {
            "request": {"include_festivals": False},
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": False,
                    "destination_id": "KR-47-130",
                },
            },
            "profile": {"audit": {"profile_active": False}},
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_direct_anchor_planner_output_to_explain() -> None:
    result = supervisor_node(
        {
            "request": {"include_festivals": False},
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": False,
                    "destination_id": "KR-47-760",
                },
            },
            "profile": {"audit": {"profile_active": False}},
            "planner": {
                "planner_output": {"itinerary": []},
                "validation_result": {"planner_status_gate": "insufficient_candidates"},
            },
        },
    )

    assert result["routing"]["next_node"] == "explain_itinerary"
    assert result["routing"]["completed_groups"] == [
        "profile",
        "festival_gate",
        "planner",
    ]


def test_supervisor_routes_confirmed_festival_anchor_to_planner() -> None:
    result = supervisor_node(
        {
            "intent": {
                "city_select_input": {
                    "country": "KR",
                    "include_festivals": True,
                    "destination_id": "KR-47-130",
                },
            },
            "profile": {"audit": {"profile_active": False}},
            "festival_gate": {
                "result": {
                    "status": "ok",
                    "allowed_city_ids": ["KR-47-130"],
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == ["profile", "festival_gate"]


def test_supervisor_routes_clarification_to_response_packager() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {
                "result": {"status": "needs_clarification"},
                "clarification": {"reason_code": "festival_tentative"},
            },
        },
    )

    assert result["routing"]["next_node"] == "response_packager"
    assert result["routing"]["needs_clarification"] is True
    assert result["routing"]["clarification_reason_code"] == "festival_tentative"


def test_supervisor_routes_modify_clarification_to_response_packager() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "modification",
                "status": "needs_clarification",
                "modify_intent": {
                    "status": "needs_clarification",
                    "routing_hint": "response_packager_wait_user",
                    "clarification": {
                        "reason_code": "modify_seed_theme_conflict",
                        "prompt": "핵심 장소는 같은 테마 안에서만 바꿀 수 있습니다.",
                        "options": [],
                    },
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "response_packager"
    assert result["routing"]["needs_clarification"] is True
    assert result["routing"]["clarification_reason_code"] == "modify_seed_theme_conflict"


def test_supervisor_routes_modify_unsupported_to_response_packager() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "modification",
                "status": "unsupported",
                "modify_intent": {
                    "status": "unsupported",
                    "routing_hint": "response_packager_notice",
                    "unsupported_reasons": ["trip_length_change"],
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "response_packager"
    assert result["routing"]["needs_clarification"] is False


def test_supervisor_routes_city_change_modify_to_planner_before_stale_response() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "modification",
                "status": "ok",
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "city_select_rediscovery",
                    "city_change": {"target_city_id": "KR-47-130"},
                },
            },
            "response": {
                "response_status": "modification_pending",
                "response_payload": {"recommendationId": "REQ-OLD"},
            },
        },
    )

    assert result["routing"]["next_node"] == "planner"


def test_supervisor_routes_city_change_planner_output_to_explain_before_stale_response() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "modification",
                "status": "ok",
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "planner_direct_anchor",
                    "city_change": {
                        "target_city_id": "KR-51-150",
                        "target_city_name": "강릉시",
                    },
                },
            },
            "planner": {
                "planner_output": {"itinerary": []},
                "validation_result": {"planner_status_gate": "ok"},
            },
            "response": {
                "response_status": "modification_pending",
                "response_payload": {"recommendationId": "REQ-OLD"},
            },
        },
    )

    assert result["routing"]["next_node"] == "explain_itinerary"


def test_supervisor_ends_after_city_change_response_payload() -> None:
    result = supervisor_node(
        {
            "intent": {
                "intent_type": "modification",
                "status": "ok",
                "modify_intent": {
                    "status": "ok",
                    "kind": "city_change",
                    "routing_hint": "planner_direct_anchor",
                    "city_change": {
                        "target_city_id": "KR-51-150",
                        "target_city_name": "강릉시",
                    },
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [],
                    "validation_result": {"planner_copy_generation_used_llm": True},
                },
            },
            "response": {
                "response_status": "modification_pending",
                "response_payload": {
                    "recommendationId": "REQ-NEW",
                    "destination": {"name": "강릉시"},
                },
            },
        },
    )

    assert result["routing"]["next_node"] == "end"


def test_supervisor_routes_city_selection_to_planner() -> None:
    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            "city_select": {"city_selection_result": {"selected_city": {"city_id": "KR-A"}}},
        },
    )

    assert result["routing"]["next_node"] == "planner"
    assert result["routing"]["completed_groups"] == [
        "profile",
        "festival_gate",
        "city_select",
    ]


def test_supervisor_finishes_after_response_payload() -> None:
    result = supervisor_node(
        {
            "response": {
                "response_status": "modification_pending",
                "response_payload": {"recommendationId": "REQ-1"},
            },
        },
    )

    assert result["routing"]["next_node"] == "end"
    assert result["routing"]["completed_groups"] == ["response"]
