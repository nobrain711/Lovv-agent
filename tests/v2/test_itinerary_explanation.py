from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

import pytest

from lovv_agent_v2.agents.response_packager.explain_itinerary import (
    ItineraryExplanationRuntime,
    explain_itinerary_node,
)
from lovv_agent_v2.agents.response_packager.planner_copy_composer import (
    validate_planner_copy_explanation_output,
)
from lovv_agent_v2.core.graph import compile_v2_graph
from lovv_agent_v2.agents.supervisor.router import route_next_action
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.models.schemas import PlannerOutput


class PlannerCopyRuntime:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[Mapping[str, Any]] = []

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(request)
        return self.response


@runtime_checkable
class InvokableGraph(Protocol):
    def invoke(self, input: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RecordingDynamoLookup:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def enrich_final_places(self, final_places: tuple[Any, ...]) -> Any:
        self.calls.append(final_places)
        enriched = tuple(
            replace(
                place,
                details={
                    "description": f"{place.title} 공개 description입니다.",
                    "overview": f"{place.title} 공개 개요입니다.",
                },
            )
            for place in final_places
        )
        return DetailResult(enriched)


class DetailResult:
    def __init__(self, places: tuple[Any, ...]) -> None:
        self.places = places
        self.warnings: tuple[Any, ...] = ()


def _planner_output() -> dict[str, Any]:
    return PlannerOutput(
        itinerary=(
            {
                "day": 1,
                "slot": "morning",
                "item_type": "attraction",
                "placeId": "P-1",
                "title": "해변",
                "body": "바다·해안 조건과 도시 내 동선을 함께 고려한 방문지입니다.",
                "reason": "요청 분위기와 테마가 함께 맞아 작업셋에 포함했습니다.",
                "moveMinutes": 0,
                "latitude": 38.2,
                "longitude": 128.6,
                "city_id": "KR-SOKCHO",
                "city_name_ko": "속초",
                "theme_tags": ("바다·해안",),
                "source": "s3_vector",
                "ddb_pk": "CITY#SOKCHO",
                "ddb_sk": "PLACE#P-1",
                "reason_code": "soft_theme_gate",
                "evidence": {"themes": ("바다·해안",)},
            },
        ),
        recommendation_reasons=("속초 안에서 바다·해안 균형을 우선했습니다.",),
        itinerary_flow_reason="도시 내 후보를 1개 일자 클러스터로 나누었습니다.",
        external_links={},
        confidence=0.76,
        user_notice=(),
        validation_result={"planner_status_gate": "ok"},
        alternative_itinerary=(),
    ).to_dict()


def _planner_output_with_modified_item() -> dict[str, Any]:
    output = _planner_output()
    output["itinerary"] = (
        output["itinerary"][0],
        {
            **output["itinerary"][0],
            "placeId": "P-2",
            "title": "새 실내 전시관",
            "body": "수정 요청에 맞춰 대체한 방문지입니다.",
            "reason": "기존 슬롯을 유지하면서 후보 적합성과 이동 가능성을 확인했습니다.",
            "copy_source": "deterministic_modify_copy",
        },
    )
    output["validation_result"] = {
        **output["validation_result"],
        "planner_copy_generation_used_llm": True,
        "itinerary_explanation_item_count": 1,
        "modification_status": "applied",
        "explanation_item_place_ids": ("P-2",),
        "applied_edit": {
            "replacement": {"content_id": "P-2", "title": "새 실내 전시관"},
        },
    }
    return output


def _state(
    runtime: ItineraryExplanationRuntime | None = None,
    *,
    runtime_bucket: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "intent": {
            "city_select_input": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "daytrip",
                "active_required_themes": ("바다·해안",),
                "include_festivals": False,
                "cleaned_raw_query": "속초 바다 산책",
                "soft_preference_query": "조용한 해안",
                "execution_mode": "anchored_place_search",
                "destination_id": "KR-SOKCHO",
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
        "planner": {"planner_output": _planner_output(), "audit": {"subgraph": "planner"}},
    }
    if runtime is not None:
        state["itinerary_explanation_runtime"] = runtime
    if runtime_bucket is not None:
        state["runtime"] = runtime_bucket
    return state


def test_explain_itinerary_only_updates_modified_items() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:1",
                        "title": "설명된 새 실내 전시관",
                        "body": "수정된 실내 전시관의 공개 설명을 바탕으로 보강했습니다.",
                        "reason": "요청한 실내 전시 분위기에 맞춰 새로 대체된 장소입니다.",
                    },
                ],
                "recommendation_reasons": ["수정된 장소만 새 설명으로 보강했습니다."],
                "itinerary_flow_reason": "기존 흐름은 유지하고 바뀐 슬롯만 설명했습니다.",
            },
        },
    )
    state = _state(
        ItineraryExplanationRuntime(
            explanation_runtime=runtime,
            dynamo_lookup=RecordingDynamoLookup(),
            schema_retry_limit=0,
        ),
    )
    planner_output = _planner_output_with_modified_item()
    planner_output["itinerary"][0]["copy_source"] = "llm_planner_copy"
    state["planner"]["planner_output"] = planner_output

    result = explain_itinerary_node(state)

    output = _planner_output_from_result(result)
    assert output["itinerary"][0]["title"] == "해변"
    assert output["itinerary"][1]["title"] == "설명된 새 실내 전시관"
    assert output["itinerary"][1]["copy_source"] == "llm_planner_copy"
    assert output["validation_result"]["modification_explanation_attempted"] is True
    assert output["validation_result"]["modification_explanation_completed"] is True
    assert len(runtime.requests) == 1


@pytest.mark.parametrize(
    "item_copies",
    [
        [],
        [
            {
                "item_ref": "item:0",
                "title": "첫 장소",
                "body": "첫 장소 설명입니다.",
                "reason": "첫 장소 추천 이유입니다.",
            },
        ],
        [
            {
                "item_ref": "item:0",
                "title": "첫 장소",
                "body": "첫 장소 설명입니다.",
                "reason": "첫 장소 추천 이유입니다.",
            },
            {
                "item_ref": "item:0",
                "title": "중복 장소",
                "body": "중복 장소 설명입니다.",
                "reason": "중복 장소 추천 이유입니다.",
            },
        ],
    ],
)
def test_planner_copy_requires_exact_scoped_item_coverage(
    item_copies: list[dict[str, str]],
) -> None:
    payload = {
        "item_copies": item_copies,
        "recommendation_reasons": ["변경 장소를 설명했습니다."],
        "itinerary_flow_reason": "기존 일정 흐름을 유지했습니다.",
    }

    with pytest.raises(SchemaValidationError):
        validate_planner_copy_explanation_output(
            payload,
            allowed_item_refs=("item:0", "item:1"),
            require_exact_item_refs=True,
        )


def test_planner_copy_accepts_exact_scoped_item_coverage() -> None:
    payload = {
        "item_copies": [
            {
                "item_ref": "item:1",
                "title": "둘째 장소",
                "body": "둘째 장소 설명입니다.",
                "reason": "둘째 장소 추천 이유입니다.",
            },
            {
                "item_ref": "item:0",
                "title": "첫 장소",
                "body": "첫 장소 설명입니다.",
                "reason": "첫 장소 추천 이유입니다.",
            },
        ],
        "recommendation_reasons": ["변경 장소를 설명했습니다."],
        "itinerary_flow_reason": "기존 일정 흐름을 유지했습니다.",
    }

    result = validate_planner_copy_explanation_output(
        payload,
        allowed_item_refs=("item:0", "item:1"),
        require_exact_item_refs=True,
    )

    assert tuple(copy["item_ref"] for copy in result["item_copies"]) == ("item:1", "item:0")


def test_invalid_scoped_copy_falls_back_without_marking_explanation_complete() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [],
                "recommendation_reasons": ["수정된 장소를 설명했습니다."],
                "itinerary_flow_reason": "기존 일정 흐름을 유지했습니다.",
            },
        },
    )
    state = _state(
        ItineraryExplanationRuntime(
            explanation_runtime=runtime,
            dynamo_lookup=RecordingDynamoLookup(),
            schema_retry_limit=0,
        ),
    )
    state["planner"]["planner_output"] = _planner_output_with_modified_item()

    output = _planner_output_from_result(explain_itinerary_node(state))

    assert output["itinerary"][1]["copy_source"] == "deterministic_modify_copy"
    assert output["validation_result"]["planner_copy_generation_used_llm"] is False
    assert output["validation_result"]["modification_explanation_attempted"] is True
    assert output["validation_result"]["modification_explanation_completed"] is False


def test_exact_multi_edit_copy_marks_every_changed_item_complete() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "설명된 첫 변경 장소",
                        "body": "첫 번째 변경 장소의 공개 정보를 바탕으로 설명했습니다.",
                        "reason": "첫 번째 수정 조건과 이동 흐름에 맞는 장소입니다.",
                    },
                    {
                        "item_ref": "item:1",
                        "title": "설명된 둘째 변경 장소",
                        "body": "두 번째 변경 장소의 공개 정보를 바탕으로 설명했습니다.",
                        "reason": "두 번째 수정 조건과 이동 흐름에 맞는 장소입니다.",
                    },
                ],
                "recommendation_reasons": ["두 변경 장소를 모두 새 설명으로 보강했습니다."],
                "itinerary_flow_reason": "기존 순서는 유지하고 두 슬롯만 교체했습니다.",
            },
        },
    )
    planner_output = _planner_output_with_modified_item()
    planner_output["itinerary"] = (
        {
            **planner_output["itinerary"][0],
            "placeId": "P-3",
            "title": "첫 변경 장소",
            "copy_source": "deterministic_modify_copy",
        },
        planner_output["itinerary"][1],
    )
    planner_output["validation_result"]["explanation_item_place_ids"] = ("P-3", "P-2")
    state = _state(
        ItineraryExplanationRuntime(
            explanation_runtime=runtime,
            dynamo_lookup=RecordingDynamoLookup(),
            schema_retry_limit=0,
        ),
    )
    state["planner"]["planner_output"] = planner_output

    output = _planner_output_from_result(explain_itinerary_node(state))

    assert [item["copy_source"] for item in output["itinerary"]] == [
        "llm_planner_copy",
        "llm_planner_copy",
    ]
    assert output["validation_result"]["modification_explanation_completed"] is True


def test_supervisor_does_not_retry_attempted_scoped_copy_fallback() -> None:
    state = _state()
    state["profile"] = {"audit": {}}
    state["festival_gate"] = {"result": None, "audit": {"skipped": True}}
    state["planner"]["planner_output"] = _planner_output_with_modified_item()
    validation = state["planner"]["planner_output"]["validation_result"]
    validation.update(
        {
            "explanation_item_place_ids": ("P-2",),
            "modification_explanation_attempted": True,
            "modification_explanation_completed": False,
            "planner_copy_generation_used_llm": False,
            "weather_audit": {"evaluation_stage": "post_explain"},
        },
    )
    state["planner"]["validation_result"] = validation

    assert route_next_action(state) == "response_packager"


def test_supervisor_routes_modified_output_back_to_explain_itinerary() -> None:
    state = _state()
    state["profile"] = {"audit": {}}
    state["festival_gate"] = {"result": None, "audit": {"skipped": True}}
    state["planner"]["planner_output"] = _planner_output_with_modified_item()
    state["planner"]["validation_result"] = state["planner"]["planner_output"]["validation_result"]

    assert route_next_action(state) == "explain_itinerary"


def test_explain_itinerary_node_uses_v1_composer_with_enriched_v2_items() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "잔잔한 속초 해변",
                        "body": "해변 공개 개요를 바탕으로 오전 산책에 맞췄습니다.",
                        "reason": "조용한 해안 선호와 직접 맞습니다.",
                    },
                ],
                "recommendation_reasons": ["속초의 해안 산책 요청에 맞춰 구성했습니다."],
                "itinerary_flow_reason": "오전 해변 산책으로 시작하는 흐름입니다.",
            },
        },
    )
    dynamo_lookup = RecordingDynamoLookup()

    result = explain_itinerary_node(
        _state(
            ItineraryExplanationRuntime(
                explanation_runtime=runtime,
                dynamo_lookup=dynamo_lookup,
                schema_retry_limit=0,
            ),
        ),
    )

    output = _planner_output_from_result(result)
    item = output["itinerary"][0]
    assert item["title"] == "잔잔한 속초 해변"
    assert item["copy_source"] == "llm_planner_copy"
    assert output["recommendation_reasons"] == ("속초의 해안 산책 요청에 맞춰 구성했습니다.",)
    assert output["validation_result"]["planner_copy_generation_used_llm"] is True
    assert "해변 공개 개요입니다." not in runtime.requests[0]["messages"][0]["content"][0]["text"]
    assert "해변 공개 description입니다." in runtime.requests[0]["messages"][0]["content"][0]["text"]
    system_prompt = json.loads(runtime.requests[0]["system"][0]["text"])
    assert system_prompt["artifact"] == "planner_copy_explanation"
    assert system_prompt["output_contract"]["body_max_chars"] == 120
    assert system_prompt["output_contract"]["body_min_guideline"] == "description이 있으면 body는 70자 이상 권장"
    assert system_prompt["output_contract"]["item_reason_length"] == "각 reason 70~130자 권장"
    assert "인적 밀도" in system_prompt["style_rules"]["congestion_claim_rule"]
    assert "해요체" in system_prompt["style_rules"]["tone"]
    assert "-한다" in system_prompt["style_rules"]["ending_style"]
    assert "-습니다" in system_prompt["style_rules"]["ending_style"]
    assert "추천해요" in system_prompt["style_rules"]["ending_style"]
    assert "함께 여행을 준비" in system_prompt["style_rules"]["friendliness_rule"]
    assert "반말" in system_prompt["style_rules"]["friendliness_rule"]
    assert "같은 종결" in system_prompt["style_rules"]["friendliness_rule"]
    assert "final_itinerary_items.overview" not in system_prompt["grounding_policy"]["allowed_sources"]
    assert system_prompt["grounding_policy"]["itinerary_scope"] == "final_itinerary_only"
    assert dynamo_lookup.calls[0][0].ddb_pk == "CITY#SOKCHO"


def test_graph_preserves_itinerary_explanation_runtime_for_copy_generation() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "그래프를 통과한 해변",
                        "body": "그래프 state의 runtime으로 생성한 설명입니다.",
                        "reason": "조용한 해안 선호와 맞습니다.",
                    },
                ],
                "recommendation_reasons": ["그래프 state의 runtime으로 설명을 생성했습니다."],
                "itinerary_flow_reason": "그래프 explain node에서 설명을 보강했습니다.",
            },
        },
    )
    graph = compile_v2_graph()
    assert isinstance(graph, InvokableGraph)
    state = _state(
        ItineraryExplanationRuntime(
            explanation_runtime=runtime,
            dynamo_lookup=RecordingDynamoLookup(),
            schema_retry_limit=0,
        ),
    )
    state["profile"] = {"audit": {}}
    state["festival_gate"] = {"result": None, "audit": {"skipped": True}}

    result = graph.invoke(state)

    output = _planner_output_from_result(result)
    item = output["itinerary"][0]
    assert item["copy_source"] == "llm_planner_copy"
    assert output["validation_result"]["planner_copy_generation_used_llm"] is True


def test_graph_scoped_copy_failure_falls_back_without_route_loop() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [],
                "recommendation_reasons": ["누락된 수정 설명입니다."],
                "itinerary_flow_reason": "수정 설명이 누락됐습니다.",
            },
        },
    )
    graph = compile_v2_graph()
    state = _state(
        ItineraryExplanationRuntime(
            explanation_runtime=runtime,
            dynamo_lookup=RecordingDynamoLookup(),
            schema_retry_limit=0,
        ),
    )
    state["profile"] = {"audit": {}}
    state["festival_gate"] = {"result": None, "audit": {"skipped": True}}
    state["planner"]["planner_output"] = _planner_output_with_modified_item()

    output = _planner_output_from_result(graph.invoke(state))

    validation = output["validation_result"]
    assert output["itinerary"][1]["copy_source"] == "deterministic_modify_copy"
    assert validation["planner_copy_generation_used_llm"] is False
    assert validation["modification_explanation_attempted"] is True
    assert validation["modification_explanation_completed"] is False
    assert len(runtime.requests) == 1


def test_explain_itinerary_node_falls_back_when_v1_composer_rejects_copy() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "top_k 점수 추천",
                        "body": "점수 기준입니다.",
                        "reason": "top_k 때문입니다.",
                    },
                ],
                "recommendation_reasons": ["내부 점수 기준입니다."],
                "itinerary_flow_reason": "점수 기준입니다.",
            },
        },
    )

    result = explain_itinerary_node(
        _state(ItineraryExplanationRuntime(explanation_runtime=runtime, schema_retry_limit=0)),
    )

    output = _planner_output_from_result(result)
    item = output["itinerary"][0]
    assert item["title"] == "해변"
    assert output["recommendation_reasons"] == ("속초 안에서 바다·해안 균형을 우선했습니다.",)
    assert output["validation_result"]["planner_copy_generation_used_llm"] is False
    assert "schema_failure" in output["explanation_audit"]["hidden_internal_notes"][-1]


def _planner_output_from_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    planner = result["planner"]
    assert isinstance(planner, Mapping)
    output = planner["planner_output"]
    assert isinstance(output, Mapping)
    return output


def test_planner_copy_rejects_internal_seed_cluster_and_relevance_terms() -> None:
    payload = {
        "item_copies": [
            {
                "item_ref": "item:0",
                "title": "해변",
                "body": "seed 장소라 추천합니다.",
                "reason": "cluster와 relevance 기준입니다.",
            },
        ],
        "recommendation_reasons": ["seed 보존을 우선했습니다."],
        "itinerary_flow_reason": "cluster 기준으로 묶었습니다.",
    }

    try:
        validate_planner_copy_explanation_output(payload, allowed_item_refs=("item:0",))
    except SchemaValidationError:
        return
    raise AssertionError("internal planner terms must be rejected")
