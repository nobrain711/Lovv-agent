from __future__ import annotations

from typing import Any

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.core.state import UnifiedAgentState


def test_intent_node_prefers_rule_city_change_over_prompt_clarification() -> None:
    runtime = RecordingIntentRuntime(
        {
            "status": "needs_clarification",
            "kind": "slot_replace",
            "edit_ops": [],
            "city_change": None,
            "clarification": {"reason_code": "modify_target_unresolved"},
            "unsupported_reasons": [],
            "routing_hint": "response_packager_wait_user",
            "audit": {"parser": "llm"},
        },
    )
    state: UnifiedAgentState = {
        "request": {
            "entryType": "modify",
            "threadId": "thread-001",
            "itineraryRevision": "rev-001",
            "rawModifyQuery": "도시는 경주로 바꿔줘.",
            "currentOrder": [{"cityId": "KR-51-170", "title": "기존 장소"}],
        },
        "intent": {
            "city_select_input": {
                "country": "KR",
                "travel_month": 9,
                "trip_type": "3d2n",
                "active_required_themes": ("자연·트레킹", "바다·해안"),
                "include_festivals": False,
                "cleaned_raw_query": "자연과 바다 여행",
            },
        },
    }

    with invocation_runtime(
        {"intent_prompt_runtime": {"runtime": runtime, "schema_retry_limit": 0}},
    ):
        output = intent_node(state)

    modify_intent = output["intent"]["modify_intent"]
    assert modify_intent["kind"] == "city_change"
    assert modify_intent["city_change"]["target_city_id"] == "KR-47-130"
    assert modify_intent["routing_hint"] == "planner_direct_anchor"
    assert output["planner"] == {}


class RecordingIntentRuntime:
    def __init__(self, structured_output: dict[str, Any]) -> None:
        self.structured_output = structured_output

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"structured_output": self.structured_output}
