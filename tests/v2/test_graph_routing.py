from __future__ import annotations

from lovv_agent_v2.agents.supervisor.router import supervisor_node
from lovv_agent_v2.agents.city_select import subgraph as city_select_subgraph
from lovv_agent_v2.agents.planner import subgraph as planner_subgraph
from lovv_agent_v2.core import graph as graph_module
from lovv_agent_v2.core.graph import compile_v2_graph, compile_v2_graph_with_nodes
from langgraph.checkpoint.memory import MemorySaver
from lovv_agent_v2.common.telemetry import trace_node


def test_graph_emits_top_level_node_metrics(capsys) -> None:
    graph = compile_v2_graph()

    graph.invoke(
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

    output = capsys.readouterr().out
    assert '"logType":"AGENT_NODE_METRIC"' in output
    assert '"nodeName":"intent"' in output
    assert '"nodeName":"supervisor"' in output
    assert '"routeNextNode":"profile"' in output


def test_city_select_subgraph_emits_internal_step_metrics(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        city_select_subgraph,
        "retrieval_node",
        lambda state: {"city_select": {"scratch": {"ok": True}}},
    )
    monkeypatch.setattr(
        city_select_subgraph,
        "scoring_and_selection_node",
        lambda state: {"city_select": {"city_selection_result": {}}},
    )
    graph = city_select_subgraph.compile_city_select_subgraph()

    graph.invoke({"request": {"request_id": "REQ-1"}})

    output = capsys.readouterr().out
    assert '"nodeName":"city_select.retrieval"' in output
    assert '"nodeName":"city_select.scoring_and_selection"' in output


def test_planner_subgraph_emits_internal_step_metrics(monkeypatch, capsys) -> None:
    monkeypatch.setattr(planner_subgraph, "retrieve_places", lambda state: {})
    monkeypatch.setattr(planner_subgraph, "route_days_step", lambda state: {})
    monkeypatch.setattr(planner_subgraph, "assemble_itinerary_step", lambda state: {})
    monkeypatch.setattr(planner_subgraph, "weather_alternative_node", lambda state: {})
    graph = planner_subgraph.compile_planner_subgraph()

    graph.invoke({"request": {"request_id": "REQ-1"}})

    output = capsys.readouterr().out
    assert '"nodeName":"planner.retrieve_places"' in output
    assert '"nodeName":"planner.route_days"' in output
    assert '"nodeName":"planner.assemble_itinerary"' in output


def test_route_loop_guard_warns_on_repeated_node_pair(capsys) -> None:
    state = {"request": {"request_id": "REQ-1"}}
    first = trace_node("loop.first", lambda node_state: {})
    second = trace_node("loop.second", lambda node_state: {})

    first(state)
    second(state)
    first(state)
    second(state)
    first(state)
    second(state)

    output = capsys.readouterr().out
    assert '"routeLoopReason":"repeated_node_pair"' in output
    assert '"routeRepeatedPair":"loop.first->loop.second"' in output
    assert '"routeRepeatedPairCount":3' in output


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


def test_graph_ends_after_current_modify_response_payload() -> None:
    state = {
        "request": {"request_id": "REQ-MOD-1"},
        "intent": {
            "modify_intent": {
                "status": "needs_clarification",
                "kind": "unsupported",
                "routing_hint": "response_packager_wait_user",
                "clarification": {
                    "reason_code": "modify_missing_current_itinerary",
                    "prompt": "수정할 기존 일정을 찾지 못했습니다.",
                    "options": [],
                },
            },
        },
        "response": {
            "response_payload": {
                "recommendationId": "REQ-MOD-1",
                "itinerary": {"days": []},
            },
        },
    }

    result = supervisor_node(state)

    assert result["routing"]["next_node"] == "end"


def test_graph_ignores_stale_response_payload_for_modify_request() -> None:
    state = {
        "request": {"request_id": "REQ-MOD-2"},
        "intent": {
            "modify_intent": {
                "status": "needs_clarification",
                "kind": "unsupported",
                "routing_hint": "response_packager_wait_user",
                "clarification": {
                    "reason_code": "modify_missing_current_itinerary",
                    "prompt": "수정할 기존 일정을 찾지 못했습니다.",
                    "options": [],
                },
            },
        },
        "response": {
            "response_payload": {
                "recommendationId": "REQ-CREATE-OLD",
                "itinerary": {"days": []},
            },
        },
    }

    result = supervisor_node(state)

    assert result["routing"]["next_node"] == "response_packager"


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
