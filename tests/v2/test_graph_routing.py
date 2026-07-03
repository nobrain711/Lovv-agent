from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node
from lovv_agent_v2.core import graph as graph_module
from lovv_agent_v2.core.graph import compile_v2_graph, compile_v2_graph_with_nodes
from langgraph.checkpoint.memory import MemorySaver


def test_graph_enters_through_generation_intent_before_supervisor() -> None:
    graph = compile_v2_graph()

    result = graph.invoke(
        {
            "intent": {
                "intent_type": "itinerary_confirmed",
                "recommendation_id": "REC-1",
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 10,
                    "travel_year": 2026,
                    "trip_type": "daytrip",
                    "active_required_themes": ("바다·해안",),
                    "include_festivals": False,
                    "cleaned_raw_query": "조용한 바다 여행",
                    "soft_preference_query": "",
                    "execution_mode": "city_discovery",
                },
            },
            "profile": {
                "lovv_user_profile": {
                    "saved_trip_count": 0,
                    "saved_theme_counts": {},
                },
            },
        },
    )

    assert result["intent"]["intent_extraction_mode"] == "provided"
    assert result["intent"]["city_select_input"]["country"] == "KR"
    assert result["profile"]["profile_update"]["reason"] == "itinerary_confirmed"
    assert result["routing"]["next_node"] == "end"


def test_graph_routes_city_select_failure_to_response_packager() -> None:
    state = {
        "city_select": {
            "city_selection_result": None,
            "status": "no_candidate",
            "clarifying_question": "조건을 조정해 주세요.",
        },
    }

    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            **state,
        },
    )

    assert result["routing"]["next_node"] == "response_packager"


def test_graph_routes_city_select_success_to_planner() -> None:
    state = {
        "city_select": {
            "city_selection_result": {
                "selected_city": {"city_id": "KR-TEST", "country": "KR"},
            },
            "status": "ok",
        },
    }

    result = supervisor_node(
        {
            "profile": {"audit": {}},
            "festival_gate": {"result": None, "audit": {"skipped": True}},
            **state,
        },
    )

    assert result["routing"]["next_node"] == "planner"


def test_parent_graph_does_not_pass_checkpointer_to_nested_subgraphs(monkeypatch) -> None:
    seen: list[object | None] = []
    checkpointer = MemorySaver()

    def fake_subgraph(*, checkpointer=None):
        seen.append(checkpointer)
        return lambda state: {}

    monkeypatch.setattr(graph_module, "compile_city_select_subgraph", fake_subgraph)
    monkeypatch.setattr(graph_module, "compile_planner_subgraph", fake_subgraph)

    compile_v2_graph_with_nodes(
        intent_handler=lambda state: {},
        profile_handler=lambda state: {},
        checkpointer=checkpointer,
    )

    assert seen == [None, None]
