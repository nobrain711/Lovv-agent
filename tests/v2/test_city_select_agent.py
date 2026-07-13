from __future__ import annotations

from collections.abc import Sequence

from pytest import MonkeyPatch

import lovv_agent_v2.agents.city_select.nodes as city_select_nodes
from lovv_agent_v2.agents.city_select.retrieval.agent import (
    CitySelectRetrievalAgent,
    CitySelectRetrievalRequest,
)
from lovv_agent_v2.tools.city_select_contracts import (
    AttractionCandidate,
    PrunedCityGroups,
)
from lovv_agent_v2.agents.city_select.subgraph import compile_city_select_subgraph
from lovv_agent_v2.tools.runtime_containers import CitySelectScoringTools, CitySelectTools


def _city_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 10,
        "travel_year": 2026,
        "trip_type": "2d1n",
        "active_required_themes": ["역사·전통"],
        "include_festivals": True,
        "cleaned_raw_query": "가을 전통 축제와 유적",
        "soft_preference_query": "",
        "unsupported_conditions": [],
        "destination_id": None,
        "user_location": None,
        "execution_mode": "festival_seeded_city_discovery",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
    }


def _discovery_city_input() -> dict[str, object]:
    payload = dict(_city_input())
    payload.update(
        {
            "include_festivals": False,
            "execution_mode": "city_discovery",
            "preferred_region_ids": ("KR-47-130", "KR-51-730"),
            "disliked_region_ids": ("KR-11-000",),
        },
    )
    return payload


def _rediscovery_city_input() -> dict[str, object]:
    payload = dict(_discovery_city_input())
    payload.update(
        {
            "preferred_region_ids": (),
            "disliked_region_ids": (),
            "disliked_city_ids": ("KR-51-170", "KR-51-150"),
        },
    )
    return payload


def test_retrieval_agent_searches_each_allowed_festival_city_directly() -> None:
    search = RecordingSearch()
    tools = CitySelectTools(
        destination_search=search,
        dynamo_lookup=RecordingDynamoLookup(),
        embedding=RecordingEmbedding(),
    )

    output = CitySelectRetrievalAgent(tools).run(
        CitySelectRetrievalRequest(
            candidate_input=_city_input(),
            allowed_city_ids=("KR-47-130", "KR-51-730", "KR-36-8"),
        ),
    )

    assert [(call["city_id"], call["theme"]) for call in search.calls] == [
        ("KR-47-130", "역사·전통"),
        ("KR-51-730", "역사·전통"),
        ("KR-36-8", "역사·전통"),
    ]
    assert None not in [call["city_id"] for call in search.calls]
    assert output.city_select["retrieval_audit"]["retrieved_candidate_count"] == 3
    assert "scratch" in output.city_select
    assert "pruned_groups" not in output.city_select


def test_retrieval_agent_applies_region_filters_to_nationwide_discovery() -> None:
    search = RecordingSearch()
    tools = CitySelectTools(
        destination_search=search,
        dynamo_lookup=RecordingDynamoLookup(),
        embedding=RecordingEmbedding(),
    )

    CitySelectRetrievalAgent(tools).run(
        CitySelectRetrievalRequest(
            candidate_input=_discovery_city_input(),
            allowed_city_ids=None,
        ),
    )

    assert search.calls == [
        {
            "city_id": None,
            "theme": "역사·전통",
            "preferred_city_ids": ("KR-47-130", "KR-51-730"),
            "disliked_city_ids": ("KR-11-000",),
        },
    ]


def test_retrieval_agent_applies_city_exclusions_to_rediscovery() -> None:
    search = RecordingSearch()
    tools = CitySelectTools(
        destination_search=search,
        dynamo_lookup=RecordingDynamoLookup(),
        embedding=RecordingEmbedding(),
    )

    CitySelectRetrievalAgent(tools).run(
        CitySelectRetrievalRequest(
            candidate_input=_rediscovery_city_input(),
            allowed_city_ids=None,
        ),
    )

    assert search.calls == [
        {
            "city_id": None,
            "theme": "역사·전통",
            "preferred_city_ids": (),
            "disliked_city_ids": ("KR-51-170", "KR-51-150"),
        },
    ]


def test_city_select_subgraph_promotes_raw_query_vector_for_planner(monkeypatch: MonkeyPatch) -> None:
    def build_tools() -> CitySelectTools:
        return CitySelectTools(
            destination_search=RecordingSearch(),
            dynamo_lookup=RecordingDynamoLookup(),
            embedding=RecordingEmbedding(),
        )

    def build_scoring_tools() -> CitySelectScoringTools:
        return CitySelectScoringTools(dynamo_lookup=RecordingDynamoLookup())

    monkeypatch.setattr(city_select_nodes, "build_default_city_select_tools", build_tools)
    monkeypatch.setattr(city_select_nodes, "build_default_city_select_scoring_tools", build_scoring_tools)

    result = compile_city_select_subgraph().invoke(
        {
            "intent": {"city_select_input": _city_input()},
            "festival_gate": {"allowed_city_ids": ("KR-47-130",)},
        },
    )

    city_select = result["city_select"]
    hints = city_select["city_selection_result"]["planner_hints"]
    assert hints["raw_query_vector"] == [0.1, 0.2]


class RecordingEmbedding:
    def embed_query(self, query: str) -> list[float]:
        assert query == "가을 전통 축제와 유적"
        return [0.1, 0.2]


class RecordingDynamoLookup:
    def city_visitor_stats(
        self,
        city_ids: Sequence[str],
        travel_month: int,
        *,
        partition_key_by_city: dict[str, str] | None = None,
    ) -> dict[str, float | None]:
        del travel_month, partition_key_by_city
        return {city_id: None for city_id in city_ids}


class RecordingSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
        preferred_city_ids: Sequence[str] = (),
        disliked_city_ids: Sequence[str] = (),
    ) -> tuple[AttractionCandidate, ...]:
        assert tuple(query_vector) == (0.1, 0.2)
        assert ddb_pk is None
        self.calls.append(
            {
                "city_id": city_id,
                "theme": theme,
                "preferred_city_ids": tuple(preferred_city_ids),
                "disliked_city_ids": tuple(disliked_city_ids),
            },
        )
        return (
            AttractionCandidate(
                key=f"{city_id}-{theme}",
                place_id=f"{city_id}-{theme}",
                distance=0.1,
                entity_type="attraction",
                city_id=city_id or "KR-NONE",
                city_name_ko="테스트시",
                title="역사 장소",
                theme_tags=(theme or "역사·전통",),
                latitude=35.1,
                longitude=129.1,
                ddb_pk=f"CITY#{city_id}",
                ddb_sk="ATTRACTION#1",
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
        assert tuple(searchable_place_themes) == ("역사·전통",)
        assert tuple(allowed_city_ids or ()) in (
            (),
            ("KR-47-130",),
            ("KR-47-130", "KR-51-730", "KR-36-8"),
        )
        return PrunedCityGroups(
            survived_groups={candidate.city_id: (candidate,) for candidate in candidates},
            eliminated_cities=(),
        )
