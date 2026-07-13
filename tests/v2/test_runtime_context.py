from __future__ import annotations

from typing import Any

import lovv_agent_v2.agents.city_select.nodes as city_select_nodes
from lovv_agent_v2.tools.travel_time_provider import HaversineTravelTimeProvider
from lovv_agent_v2.agents.planner.state.context import runtime_tools, travel_time_provider
from lovv_agent_v2.tools.runtime_containers import PlannerRuntimeTools
from lovv_agent_v2.agents.response_packager.explain_itinerary import (
    ItineraryExplanationRuntime,
    explain_itinerary_node,
)
from lovv_agent_v2.core.runtime_state import invocation_runtime
from tests.v2.test_runtime_dependency_injection import (
    PlannerCopyRuntime,
    RecordingEmbedding,
    RecordingSearch,
    _city_input,
    _city_select_tools,
    _explanation_state,
    _fail_retrieval_tools,
)


def test_city_select_retrieval_reads_invocation_runtime_tools(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        city_select_nodes,
        "build_default_city_select_tools",
        _fail_retrieval_tools,
    )

    with invocation_runtime({"city_select_tools": _city_select_tools()}):
        result = city_select_nodes.retrieval_node(
            {"intent": {"city_select_input": _city_input()}},
        )

    assert result["city_select"]["retrieval_audit"]["retrieved_candidate_count"] == 1


def test_planner_context_reads_invocation_runtime_dependencies() -> None:
    provider = HaversineTravelTimeProvider()
    planner_runtime = PlannerRuntimeTools(
        destination_search=RecordingSearch(),
        embedding=RecordingEmbedding(),
    )

    with invocation_runtime(
        {
            "planner_runtime": planner_runtime,
            "travel_time_provider": provider,
        },
    ):
        assert runtime_tools({}) == planner_runtime
        assert travel_time_provider({}) is provider


def test_response_packager_reads_invocation_runtime_for_planner_copy() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "바다 산책로",
                        "body": "해안을 따라 걷기 좋은 장소",
                        "reason": "요청한 바다 분위기와 맞음",
                    },
                ],
                "recommendation_reasons": ["바다 중심 일정입니다."],
                "itinerary_flow_reason": "해안 산책 후 쉬는 흐름입니다.",
            },
        },
    )

    with invocation_runtime(
        {
            "itinerary_explanation_runtime": ItineraryExplanationRuntime(
                explanation_runtime=runtime,
                schema_retry_limit=0,
            ),
        },
    ):
        output = explain_itinerary_node(_explanation_state())["planner"]["planner_output"]

    assert output["itinerary"][0]["copy_source"] == "llm_planner_copy"
    assert runtime.requests
