from __future__ import annotations

from lovv_agent_v2.agentcore_entrypoint import extract_graph_payload


def test_extract_graph_payload_accepts_modify_request_without_create_fields() -> None:
    payload = extract_graph_payload(
        {
            "entryType": "modify",
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 장소를 조용한 산책지로 바꿔줘.",
            "currentOrder": [],
        },
        request_id="REQ-MODIFY",
    )

    assert payload == {
        "request": {
            "entryType": "modify",
            "request_id": "REQ-MODIFY",
            "threadId": "thread-001",
            "thread_id": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 장소를 조용한 산책지로 바꿔줘.",
            "currentOrder": [],
        },
        "profile": {},
    }


def test_extract_graph_payload_maps_session_id_to_followup_thread_id() -> None:
    payload = extract_graph_payload(
        {
            "entryType": "modify",
            "sessionId": "session-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "1일차 오후 장소를 바꿔줘.",
            "currentOrder": [],
        },
        request_id="REQ-MODIFY",
    )

    assert payload["request"]["thread_id"] == "session-001"


def test_extract_graph_payload_accepts_clarify_request_without_create_fields() -> None:
    payload = extract_graph_payload(
        {
            "entryType": "clarify",
            "threadId": "thread-001",
            "selectedOptionId": "continue_without_festival",
        },
        request_id="REQ-CLARIFY",
    )

    assert payload == {
        "request": {
            "entryType": "clarify",
            "request_id": "REQ-CLARIFY",
            "threadId": "thread-001",
            "thread_id": "thread-001",
            "selectedOptionId": "continue_without_festival",
        },
        "profile": {},
    }


def test_extract_graph_payload_accepts_confirm_request_without_create_fields() -> None:
    payload = extract_graph_payload(
        {
            "entryType": "confirm",
            "threadId": "thread-001",
            "recommendationId": "rec-001",
            "itineraryRevision": "rev-001",
        },
        request_id="REQ-CONFIRM",
    )

    assert payload == {
        "request": {
            "entryType": "confirm",
            "request_id": "REQ-CONFIRM",
            "threadId": "thread-001",
            "thread_id": "thread-001",
            "recommendationId": "rec-001",
            "itineraryRevision": "rev-001",
        },
        "profile": {},
    }
