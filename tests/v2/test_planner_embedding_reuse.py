from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Event

from lovv_agent_v2.agents.planner.state_adapter import retrieve_places


def _place(place_id: str, title: str, theme: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "latitude": 38.2,
        "longitude": 128.6,
        "distance": 0.1,
    }


class FakeEmbedding:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [1.0, 0.5]


@dataclass(frozen=True, slots=True)
class SearchCall:
    vector: Sequence[float]
    top_k: int
    city_id: str | None
    ddb_pk: str | None
    theme: str | None


class FakeDestinationSearch:
    def __init__(self) -> None:
        self.calls: list[SearchCall] = []

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(
            SearchCall(
                vector=query_vector,
                top_k=top_k,
                city_id=city_id,
                ddb_pk=ddb_pk,
                theme=theme,
            ),
        )
        if len(self.calls) == 1:
            return (_place("raw-1", "해변", "바다·해안"),)
        return (_place("soft-1", "향교", "역사·문화"),)


@dataclass(frozen=True, slots=True)
class FakePlannerTools:
    destination_search: FakeDestinationSearch
    embedding: FakeEmbedding


def test_retrieve_places_reuses_city_select_raw_query_vector_for_initial_generation() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state: dict[str, object] = {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 역사",
                "soft_preference_query": "조용한 역사 산책",
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안", "역사·문화"],
                "transport_pref": "car",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "ddb_pk": "CITY#SOKCHO",
                },
                "alternative_city": None,
                "seeds": [],
                "planner_hints": {"raw_query_vector": [9.0, 8.0]},
            },
        },
        "planner": {
            "scratch": {
                "runtime": FakePlannerTools(
                    destination_search=search,
                    embedding=embedding,
                ),
            },
        },
    }

    result = retrieve_places(state)

    planner = result["planner"]
    assert isinstance(planner, dict)
    scratch = planner["scratch"]
    assert isinstance(scratch, dict)
    pool = scratch["place_pool"]
    assert isinstance(pool, dict)
    raw_places = pool["raw_places"]
    assert isinstance(raw_places, tuple)
    assert embedding.queries == ["조용한 역사 산책"]
    assert tuple(search.calls[0].vector) == (9.0, 8.0)
    assert search.calls[1].vector == [1.0, 0.5]
    assert [call.top_k for call in search.calls] == [50, 50]
    assert [place["place_id"] for place in raw_places] == ["raw-1"]


class BlockingSearch:
    def __init__(self) -> None:
        self.raw_started = Event()
        self.soft_started = Event()

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        del top_k, city_id, ddb_pk, theme
        if tuple(query_vector) == (9.0, 8.0):
            self.raw_started.set()
            assert self.soft_started.wait(1.0)
            return (_place("raw-1", "해변", "바다·해안"),)
        self.soft_started.set()
        assert self.raw_started.wait(1.0)
        return (_place("soft-1", "향교", "역사·전통"),)


def test_retrieve_places_runs_raw_and_soft_searches_in_parallel() -> None:
    search = BlockingSearch()
    state: dict[str, object] = {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 역사",
                "soft_preference_query": "조용한 역사 산책",
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안", "역사·전통"],
                "transport_pref": "car",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {"city_id": "KR-SOKCHO", "city_name_ko": "속초"},
                "alternative_city": None,
                "seeds": [],
                "planner_hints": {"raw_query_vector": [9.0, 8.0]},
            },
        },
        "planner": {
            "scratch": {
                "runtime": FakePlannerTools(
                    destination_search=search,
                    embedding=FakeEmbedding(),
                ),
            },
        },
    }

    result = retrieve_places(state)

    pool = result["planner"]["scratch"]["place_pool"]
    assert isinstance(pool, dict)
    assert len(pool["raw_places"]) == 1
    assert len(pool["soft_places"]) == 1
