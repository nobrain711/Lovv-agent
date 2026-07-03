from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import lovv_agent_v2.agents.city_select.nodes as city_select_nodes
from lovv_agent_v2.agents.city_select.domain.contracts import (
    AttractionCandidate,
    PrunedCityGroups,
    prepare_city_select_context,
)
from lovv_agent_v2.agents.city_select.retrieval.flow import (
    city_select_failure_state as _city_select_failure_state,
    package_failure as _package_failure,
)
from lovv_agent_v2.agents.city_select.subgraph import compile_city_select_subgraph
from lovv_agent_v2.agents.city_select.tools import CitySelectTools
from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool


def _city_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 10,
        "travel_year": 2026,
        "trip_type": "2d1n",
        "active_required_themes": ["바다·해안"],
        "include_festivals": False,
        "cleaned_raw_query": "바다 여행",
        "soft_preference_query": "",
        "unsupported_conditions": [],
        "destination_id": None,
        "user_location": None,
        "execution_mode": "city_discovery",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
        "preferred_theme_ids": ("sea_coast",),
        "disliked_theme_ids": ("nature_trekking",),
    }


def test_unified_agent_state_exposes_v2_23_top_level_groups() -> None:
    assert UnifiedAgentState.__optional_keys__ == {
        "request",
        "intent",
        "profile",
        "festival_gate",
        "city_select",
        "planner",
        "response",
        "routing",
        "memory",
        "trace",
    }


def test_planner_agent_and_tools_do_not_import_unified_state() -> None:
    root = Path(__file__).parents[2]
    for relative_path in (
        "src/lovv_agent_v2/agents/planner/agent.py",
        "src/lovv_agent_v2/agents/planner/tools.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "UnifiedAgentState" not in source
        assert "lovv_agent_v2.core.state" not in source


def test_planner_agent_keeps_state_adapter_out_of_core_orchestration() -> None:
    root = Path(__file__).parents[2]
    agent_source = (root / "src/lovv_agent_v2/agents/planner/agent.py").read_text(encoding="utf-8")
    tools_source = (root / "src/lovv_agent_v2/agents/planner/tools.py").read_text(encoding="utf-8")

    for forbidden in (
        "planner.state.context",
        "planner.state.scratch",
        "planner_state_update",
        "planner_scratch",
        "assemble_itinerary_node",
        "fallback_to_alternative_city_node",
    ):
        assert forbidden not in agent_source

    assert "scratch" not in tools_source


def test_planner_node_implementation_files_are_grouped_by_subgraph_step() -> None:
    planner_root = Path(__file__).parents[2] / "src/lovv_agent_v2/agents/planner"
    expected_step_files = (
        "steps/retrieve_places/festival_seed.py",
        "steps/route_days/day_profile.py",
        "steps/route_days/place_selection.py",
        "steps/route_days/routing.py",
        "steps/route_days/subtype_diversity.py",
        "steps/assemble_itinerary/node.py",
        "steps/retry_alternative_city/node.py",
        "domain/place_model.py",
        "state/context.py",
        "state/scratch.py",
        "external/travel_time.py",
        "external/ors_provider.py",
        "external/agentcore_credentials.py",
    )
    legacy_root_files = (
        "nodes.py",
        "context.py",
        "scratch.py",
        "place_model.py",
        "travel_time.py",
        "ors_provider.py",
        "ors_results.py",
        "agentcore_credentials.py",
        "in_city_itinerary.py",
        "compat/in_city_itinerary.py",
        "assemble.py",
        "fallback.py",
        "festival_seed.py",
        "day_profile.py",
        "edit_mode.py",
        "place_selection.py",
        "plan_b.py",
        "routing.py",
        "subtype_diversity.py",
        "validation.py",
    )

    for relative_path in expected_step_files:
        assert (planner_root / relative_path).exists()
    for relative_path in legacy_root_files:
        assert not (planner_root / relative_path).exists()


def test_profile_node_writes_city_select_input_and_profile_state() -> None:
    result = profile_node(
        {
            "intent": {"city_select_input": _city_input()},
            "profile": {
                "profile_record": {
                    "profile_id": "P-sea",
                    "lovv_user_profile": {
                        "saved_trip_count": 3,
                        "saved_theme_counts": {"sea_coast": 3},
                    },
                },
            },
        },
    )

    assert "city_select_input" in result["intent"]
    assert result["intent"]["trip_intent"]["themes"] == ("바다·해안",)
    assert result["intent"]["trip_intent"]["theme_weights"] == {"바다·해안": 1.3}
    assert result["intent"]["trip_intent"]["preferred_theme_ids"] == ("sea_coast",)
    assert result["intent"]["trip_intent"]["disliked_theme_ids"] == ("nature_trekking",)
    assert result["profile"]["applied_persona_id"] == "P-sea"
    assert result["profile"]["effective_theme_weights"] == {"바다·해안": 1.3}
    assert "profile_result" not in result["profile"]


def test_city_select_failure_uses_city_select_state_contract() -> None:
    context = prepare_city_select_context(_city_input())
    result = _package_failure(
        context,
        status="no_candidate",
        failure_signal="no_searchable_place_theme",
        needs_clarification=True,
        clarifying_question="조건을 조정해 주세요.",
    )

    state = _city_select_failure_state(result)

    assert state["city_selection_result"] is None
    assert state["status"] == "no_candidate"
    assert state["failure_signals"] == ("no_searchable_place_theme",)
    assert state["clarifying_question"] == "조건을 조정해 주세요."


def test_city_select_does_not_run_festival_lookup_without_gate_result() -> None:
    city_input = _city_input()
    city_input["include_festivals"] = True

    result = city_select_nodes.retrieval_node({"intent": {"city_select_input": city_input}})

    city_select = result["city_select"]
    assert city_select["status"] == "error"
    assert city_select["failure_signals"] == ("missing_festival_gate_allowed_city_ids",)
    assert city_select["retrieval_audit"]["festival_gate_required"] is True


def test_city_select_retrieval_keeps_internal_handoff_in_scratch(monkeypatch: Any) -> None:
    def build_tools(*args: object) -> CitySelectTools:
        return CitySelectTools(
            destination_search=RecordingSearch(),
            dynamo_lookup=RecordingDynamoLookup(),
            embedding=RecordingEmbedding(),
        )

    monkeypatch.setattr(city_select_nodes, "build_default_city_select_tools", build_tools)

    result = city_select_nodes.retrieval_node({"intent": {"city_select_input": _city_input()}})

    city_select = result["city_select"]
    assert "scratch" in city_select
    assert "pruned_groups" not in city_select
    assert "context" not in city_select
    assert "festival_seed_result" not in city_select
    assert city_select["retrieval_audit"]["retrieved_candidate_count"] == 1
    assert city_select["scoring_audit"] == {}


def test_city_select_subgraph_drops_scratch_from_final_state(monkeypatch: Any) -> None:
    def build_tools(*args: object) -> CitySelectTools:
        return CitySelectTools(
            destination_search=RecordingSearch(),
            dynamo_lookup=RecordingDynamoLookup(),
            embedding=RecordingEmbedding(),
        )

    def city_visitor_stats(
        self: DynamoLookupTool,
        city_ids: Sequence[str],
        travel_month: int,
        *,
        partition_key_by_city: dict[str, str] | None = None,
    ) -> dict[str, float | None]:
        return {city_id: None for city_id in city_ids}

    monkeypatch.setattr(city_select_nodes, "build_default_city_select_tools", build_tools)
    monkeypatch.setattr(DynamoLookupTool, "city_visitor_stats", city_visitor_stats)

    result = compile_city_select_subgraph().invoke({"intent": {"city_select_input": _city_input()}})

    city_select = result["city_select"]
    assert "scratch" not in city_select
    assert "pruned_groups" not in city_select
    assert "context" not in city_select
    assert "festival_seed_result" not in city_select
    assert city_select["city_selection_result"]["selected_city"]["city_id"] == "KR-TEST"


class RecordingEmbedding:
    def embed_query(self, query: str) -> list[float]:
        assert query == "바다 여행"
        return [0.1, 0.2]


class RecordingDynamoLookup:
    def city_visitor_stats(
        self,
        city_ids: Sequence[str],
        travel_month: int,
        *,
        partition_key_by_city: dict[str, str] | None = None,
    ) -> dict[str, float | None]:
        return {city_id: None for city_id in city_ids}


class RecordingSearch:
    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        assert tuple(query_vector) == (0.1, 0.2)
        assert city_id is None
        assert ddb_pk is None
        assert theme == "바다·해안"
        return (
            AttractionCandidate(
                key="P1",
                place_id="P1",
                distance=0.1,
                entity_type="attraction",
                city_id="KR-TEST",
                city_name_ko="테스트시",
                title="바다 장소",
                theme_tags=("바다·해안",),
                latitude=35.1,
                longitude=129.1,
                ddb_pk="CITY#TEST",
                ddb_sk="ATTRACTION#P1",
                metadata={},
            ),
        )

    def prune_cities(
        self,
        candidates: Sequence[AttractionCandidate],
        searchable_place_themes: Sequence[str],
        *,
        allowed_city_ids: Sequence[str] | None = None,
    ) -> PrunedCityGroups:
        assert tuple(searchable_place_themes) == ("바다·해안",)
        assert allowed_city_ids is None
        return PrunedCityGroups(
            survived_groups={"KR-TEST": tuple(candidates)},
            eliminated_cities=(),
        )
