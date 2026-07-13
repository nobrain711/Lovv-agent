from __future__ import annotations

from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_response_packager_packages_failed_slot_replace_clarification(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {"selectedOptionId": "keep_current_place"},
    )

    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "첫 장소 말고 조용한 숲길로 바꿔줘.",
            },
            "intent": {
                "intent_type": "modification",
                "modify_intent": {
                    "status": "ok",
                    "kind": "slot_replace",
                    "routing_hint": "planner_apply_edit",
                    "edit_ops": [{"op_id": "op-1"}],
                },
            },
            "planner": {
                "modify_context": {
                    "failed_edit": {
                        "reason_code": "slot_replace_no_candidate",
                        "target": {"title": "이전 장소"},
                    },
                },
            },
        },
    )

    response = result["response"]
    payload = result["response"]["response_payload"]
    assert response["response_status"] == "END_WAIT_USER"
    assert payload["itinerary"]["days"] == []
    assert payload["clarification"]["reasonCode"] == "slot_replace_no_candidate"
    assert response["clarification_resume"]["option_id"] == "keep_current_place"
    assert response["clarification_resume"]["then"] == "abort"


def test_response_packager_packages_unresolved_slot_clarification(monkeypatch) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {"selectedOptionId": "revise_slot_target"},
    )

    result = response_packager_node(
        {
            "request": {
                "entryType": "modify",
                "threadId": "thread-001",
                "itineraryRevision": "rev-001",
                "rawModifyQuery": "4일차 2번째 장소 바꿔줘.",
            },
            "intent": {
                "intent_type": "modification",
                "modify_intent": {
                    "status": "ok",
                    "kind": "slot_replace",
                    "routing_hint": "planner_apply_edit",
                    "edit_ops": [{"op_id": "op-1"}],
                },
            },
            "planner": {
                "modify_context": {
                    "failed_edit": {
                        "reason_code": "modify_target_unresolved",
                        "requested_target": {"day": 4, "order": 2},
                    },
                },
            },
        },
    )

    response = result["response"]
    payload = response["response_payload"]
    assert response["response_status"] == "END_WAIT_USER"
    assert payload["clarification"]["reasonCode"] == "modify_target_unresolved"
    assert "몇 번째 장소" in payload["explainability"]["userNotice"]
    assert payload["clarification"]["options"][0]["optionId"] == "revise_slot_target"
