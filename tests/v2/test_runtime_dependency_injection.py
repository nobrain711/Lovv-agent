from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import lovv_agent_v2.agents.city_select.nodes as city_select_nodes
from lovv_agent_v2.tools.city_select_contracts import AttractionCandidate, PrunedCityGroups
from lovv_agent_v2.agents.planner.state.context import runtime_tools, travel_time_provider
from lovv_agent_v2.tools.travel_time_provider import HaversineTravelTimeProvider
from lovv_agent_v2.agents.response_packager.explain_itinerary import explain_itinerary_node
from lovv_agent_v2.tools.runtime_containers import (
    CitySelectScoringTools,
    CitySelectTools,
    ItineraryExplanationRuntime,
    PlannerRuntimeTools,
)
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.models.schemas import PlannerOutput


class PlannerCopyRuntime:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return self.response


def test_city_select_retrieval_uses_runtime_bucket_tools(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        city_select_nodes,
        "build_default_city_select_tools",
        _fail_retrieval_tools,
    )

    result = city_select_nodes.retrieval_node(
        {
            "intent": {"city_select_input": _city_input()},
            "runtime": {"city_select_tools": _city_select_tools()},
        },
    )

    assert result["city_select"]["retrieval_audit"]["retrieved_candidate_count"] == 1


def test_city_select_scoring_uses_runtime_bucket_tools(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        city_select_nodes,
        "build_default_city_select_scoring_tools",
        _fail_scoring_tools,
    )
    monkeypatch.setattr(
        DynamoLookupTool,
        "city_visitor_stats",
        _city_visitor_stats,
    )
    retrieval = city_select_nodes.retrieval_node(
        {
            "intent": {"city_select_input": _city_input()},
            "runtime": {"city_select_tools": _city_select_tools()},
        },
    )

    result = city_select_nodes.scoring_and_selection_node(
        {
            **retrieval,
            "runtime": {
                "city_select_scoring_tools": CitySelectScoringTools(
                    dynamo_lookup=RecordingDynamoLookup(),
                ),
            },
        },
    )

    assert result["city_select"]["city_selection_result"]["selected_city"]["city_id"] == "KR-TEST"


def test_planner_context_reads_runtime_bucket_dependencies() -> None:
    provider = HaversineTravelTimeProvider()
    planner_runtime = PlannerRuntimeTools(
        destination_search=RecordingSearch(),
        embedding=RecordingEmbedding(),
    )

    state = {
        "runtime": {
            "planner_runtime": planner_runtime,
            "travel_time_provider": provider,
        },
    }

    assert runtime_tools(state) == planner_runtime
    assert travel_time_provider(state) is provider


def test_response_packager_reads_runtime_bucket_for_planner_copy() -> None:
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

    output = explain_itinerary_node(
        {
            **_explanation_state(),
            "runtime": {
                "itinerary_explanation_runtime": ItineraryExplanationRuntime(
                    explanation_runtime=runtime,
                    schema_retry_limit=0,
                ),
            },
        },
    )["planner"]["planner_output"]

    assert output["itinerary"][0]["copy_source"] == "llm_planner_copy"
    assert output["validation_result"]["planner_copy_generation_used_llm"] is True
    assert runtime.requests


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
    }


def _city_select_tools() -> CitySelectTools:
    return CitySelectTools(
        destination_search=RecordingSearch(),
        dynamo_lookup=RecordingDynamoLookup(),
        embedding=RecordingEmbedding(),
    )


def _fail_retrieval_tools() -> CitySelectTools:
    raise AssertionError("default city_select retrieval tools should not be used")


def _fail_scoring_tools() -> CitySelectScoringTools:
    raise AssertionError("default city_select scoring tools should not be used")


def _city_visitor_stats(
    self: DynamoLookupTool,
    city_ids: Sequence[str],
    travel_month: int,
    *,
    partition_key_by_city: dict[str, str] | None = None,
) -> dict[str, float | None]:
    return {city_id: None for city_id in city_ids}


class RecordingEmbedding:
    def embed_query(self, query: str) -> list[float]:
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
        return PrunedCityGroups(
            survived_groups={"KR-TEST": tuple(candidates)},
            eliminated_cities=(),
        )


def _explanation_state() -> dict[str, Any]:
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 산책",
                "soft_preference_query": "조용한 해안",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "country": "KR",
                    "selection_reason_code": ("theme_city_match",),
                },
            },
        },
        "planner": {"planner_output": _planner_output()},
    }


def _planner_output() -> dict[str, Any]:
    return PlannerOutput(
        itinerary=(
            {
                "day": 1,
                "slot": "morning",
                "item_type": "attraction",
                "placeId": "P-1",
                "title": "해변",
                "body": "fallback",
                "reason": "fallback",
                "moveMinutes": 0,
                "latitude": 38.2,
                "longitude": 128.6,
                "city_id": "KR-SOKCHO",
                "city_name_ko": "속초",
                "theme_tags": ("바다·해안",),
                "source": "s3_vector",
            },
        ),
        recommendation_reasons=("속초 해안 일정입니다.",),
        itinerary_flow_reason="해안 중심 흐름입니다.",
        external_links={},
        confidence=0.76,
        user_notice=(),
        validation_result={"planner_status_gate": "ok"},
        alternative_itinerary=(),
    ).to_dict()
