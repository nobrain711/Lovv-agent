from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from lovv_agent_v2.core.mock_graph import compile_v2_mock_graph
from lovv_agent_v2.core.graph import compile_v2_graph_with_nodes
from lovv_agent_v2.harness import LovvLangGraphV2Harness
from lovv_agent_v2.infra.config import RuntimeConfig


class _InterruptState(TypedDict, total=False):
    prompt: str
    decision: str
    status: str


class _NonSerializableTool:
    def __init__(self) -> None:
        self.callback = lambda value: value


def test_langgraph_interrupt_resume_contract_matches_agentcore_pattern() -> None:
    workflow = StateGraph(_InterruptState)
    workflow.add_node("ask", _ask_node)
    workflow.add_node("finish", _finish_node)
    workflow.add_edge(START, "ask")
    workflow.add_edge("ask", "finish")
    workflow.add_edge("finish", END)
    graph = workflow.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "v2-interrupt-contract"}}

    first = graph.invoke({"prompt": "festival fallback"}, config=config)

    assert "__interrupt__" in first
    assert graph.get_state(config).next == ("ask",)

    second = graph.invoke(Command(resume="CONTINUE_WITHOUT_FESTIVAL"), config=config)

    assert second["decision"] == "CONTINUE_WITHOUT_FESTIVAL"
    assert second["status"] == "completed"


def test_modification_pending_checkpoint_accepts_confirmation_on_same_thread() -> None:
    graph = compile_v2_mock_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "v2-modification-pending-confirm"}}

    first = graph.invoke(_ready_to_package_state(), config=config)

    assert first["response"]["response_status"] == "modification_pending"
    assert (
        graph.get_state(config).values["response"]["response_status"]
        == "modification_pending"
    )

    second = graph.invoke(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REQ-CHECKPOINT",
            },
        },
        config=config,
    )

    assert second["profile"]["profile_update"]["status"] == "recorded"
    assert (
        graph.get_state(config).values["profile"]["profile_update"]["reason"]
        == "itinerary_confirmed"
    )


def test_runtime_tools_are_not_checkpointed_with_harness_context() -> None:
    graph = compile_v2_mock_graph(checkpointer=MemorySaver())
    harness = LovvLangGraphV2Harness(
        graph=graph,
        config=RuntimeConfig(),
        runtime={"planner_runtime": _NonSerializableTool()},
    )
    config = {"configurable": {"thread_id": "v2-runtime-context-safe"}}

    first = harness.invoke(_ready_to_package_state(), graph_config=config)

    assert first["response"]["response_status"] == "modification_pending"
    assert "runtime" not in graph.get_state(config).values


def test_weather_clarification_resumes_from_response_packager_checkpoint() -> None:
    graph = compile_v2_graph_with_nodes(
        intent_handler=lambda state: {},
        profile_handler=lambda state: {"profile": {"audit": {}}},
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "v2-weather-resume", "actor_id": "v2-weather-resume"}}

    first = graph.invoke(_weather_alternative_state(), config=config)

    assert "__interrupt__" in first
    interrupt_payload = first["__interrupt__"][0].value
    assert interrupt_payload["clarification"]["reasonCode"] == "weather_alternative_available"

    second = graph.invoke(
        Command(resume={"selectedOptionId": "keep_primary_itinerary"}),
        config=config,
    )

    assert second["response"]["response_status"] == "modification_pending"
    assert second["response"]["clarification_resume"]["option_id"] == "keep_primary_itinerary"


def _ask_node(state: _InterruptState) -> dict[str, str]:
    if state.get("decision"):
        return {}
    decision = interrupt(
        {"status": "INTERRUPTED", "options": ["CONTINUE_WITHOUT_FESTIVAL"]},
    )
    return {"decision": str(decision)}


def _finish_node(state: _InterruptState) -> dict[str, str]:
    return {"status": "completed", "decision": state["decision"]}


def _ready_to_package_state() -> dict[str, object]:
    return {
        "request": {
            "request_id": "REQ-CHECKPOINT",
            "country": "KR",
            "travel_month": 7,
            "travel_year": 2026,
            "trip_type": "daytrip",
            "destination_id": "KR-51-150",
            "include_festivals": False,
            "themes": ("바다·해안",),
            "active_required_themes": ("바다·해안",),
        },
        "intent": {
            "intent_output": {
                "country": "KR",
                "travel_month": 7,
                "travel_year": 2026,
                "trip_type": "daytrip",
                "destination_id": "KR-51-150",
                "include_festivals": False,
                "active_required_themes": ["바다·해안"],
                "cleaned_raw_query": "강릉 바다 당일 여행",
                "soft_preference_query": "",
                "congestion_pref": "neutral",
                "transport_pref": "car",
                "unsupported_conditions": [],
            },
        },
        "profile": {"audit": {"profile_active": False}},
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-51-150",
                    "city_name_ko": "강릉시",
                    "country": "KR",
                    "selection_reason_code": ["direct_anchor"],
                },
            },
        },
        "planner": {
            "planner_output": {
                "itinerary": [
                    {
                        "day": 1,
                        "slot": "morning",
                        "placeId": "place-1",
                        "title": "경포해변",
                        "body": "해안 산책을 시작하기 좋은 장소입니다.",
                        "reason": "바다·해안 테마와 맞습니다.",
                        "city_id": "KR-51-150",
                        "city_name_ko": "강릉시",
                    },
                ],
                "recommendation_reasons": ("강릉 해안 동선 중심 일정입니다.",),
                "itinerary_flow_reason": "해변에서 시작하는 짧은 당일 동선입니다.",
                "external_links": {},
                "confidence": 0.8,
                "user_notice": (),
                "validation_result": {"itinerary_explanation_item_count": 1},
            },
            "validation_result": {"itinerary_explanation_item_count": 1},
        },
    }


def _weather_alternative_state() -> dict[str, object]:
    state = _ready_to_package_state()
    planner = dict(state["planner"])
    planner_output = dict(planner["planner_output"])
    validation = dict(planner_output["validation_result"])
    validation["itinerary_explanation_item_count"] = 1
    validation["weather_audit"] = {
        "status": "alternative_available",
        "evaluation_stage": "post_explain",
    }
    planner_output["validation_result"] = validation
    planner["planner_output"] = planner_output
    planner["validation_result"] = validation
    state["planner"] = planner
    return state
