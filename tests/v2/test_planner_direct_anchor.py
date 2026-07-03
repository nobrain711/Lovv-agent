from __future__ import annotations

from dataclasses import dataclass
from typing import cast

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
        return [float(len(self.queries)), 0.5]


class FakeDestinationSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_candidates(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(
            {
                "vector": query_vector,
                "top_k": top_k,
                "city_id": city_id,
                "ddb_pk": ddb_pk,
                "theme": theme,
            },
        )
        if len(self.calls) == 1:
            return (
                _place("raw-1", "해변", "바다·해안"),
                _place("raw-2", "등대", "바다·해안"),
            )
        return (_place("soft-1", "향교", "역사·문화"),)


@dataclass(frozen=True, slots=True)
class FakePlannerTools:
    destination_search: FakeDestinationSearch
    embedding: FakeEmbedding


def test_retrieve_places_node_uses_direct_anchor_without_city_select() -> None:
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
                "destination_id": "KR-SOKCHO",
                "city_key": "CITY#SOKCHO",
                "include_festivals": False,
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

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    raw_places = cast(tuple[dict[str, object], ...], pool["raw_places"])
    assert embedding.queries == ["속초 바다 역사", "조용한 역사 산책"]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO", "KR-SOKCHO"]
    assert [call["ddb_pk"] for call in search.calls] == [None, None]
    assert [place["place_id"] for place in raw_places] == ["raw-1", "raw-2"]


def test_retrieve_places_node_treats_empty_city_select_as_direct_anchor() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state: dict[str, object] = {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "경주 역사 여행",
                "soft_preference_query": "고도 산책",
                "trip_type": "2d1n",
                "active_required_themes": ["역사·문화"],
                "transport_pref": "car",
                "destination_id": "KR-47-130",
                "destination_label": "경주시",
                "include_festivals": False,
            },
        },
        "city_select": {},
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

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    raw_places = cast(tuple[dict[str, object], ...], pool["raw_places"])
    assert [call["city_id"] for call in search.calls] == ["KR-47-130", "KR-47-130"]
    assert [place["place_id"] for place in raw_places] == ["raw-1", "raw-2"]


def test_retrieve_places_node_prefers_trip_intent_for_direct_anchor() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state: dict[str, object] = {
        "intent": {
            "trip_intent": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "themes": ("바다·해안", "역사·문화"),
                "include_festivals": False,
                "raw_query": "속초 바다 역사",
                "soft_preference_query": "조용한 역사 산책",
                "transport_pref": "car",
                "destination_id": "KR-SOKCHO",
                "city_key": "CITY#SOKCHO",
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

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    raw_places = cast(tuple[dict[str, object], ...], pool["raw_places"])
    assert embedding.queries == ["속초 바다 역사", "조용한 역사 산책"]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO", "KR-SOKCHO"]
    assert [place["place_id"] for place in raw_places] == ["raw-1", "raw-2"]


def test_retrieve_places_node_keeps_preferred_theme_as_selection_hint_only() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state: dict[str, object] = {
        "intent": {
            "trip_intent": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "daytrip",
                "themes": ("바다·해안",),
                "preferred_theme_ids": ("history_tradition",),
                "include_festivals": False,
                "raw_query": "속초 바다 여행",
                "soft_preference_query": "",
                "transport_pref": "car",
                "destination_id": "KR-SOKCHO",
                "city_key": "CITY#SOKCHO",
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

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    raw_places = cast(tuple[dict[str, object], ...], pool["raw_places"])
    assert [call["theme"] for call in search.calls] == [None]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO"]
    assert [place["place_id"] for place in raw_places] == ["raw-1", "raw-2"]


def test_retrieve_places_node_uses_confirmed_festival_anchor_without_city_select() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state: dict[str, object] = {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "경주 전통 축제",
                "soft_preference_query": "유적 산책",
                "trip_type": "2d1n",
                "active_required_themes": ["역사·문화"],
                "transport_pref": "car",
                "destination_id": "KR-47-130",
                "city_key": "CITY#GYEONGJU",
                "include_festivals": True,
            },
        },
        "festival_gate": {
            "result": {
                "status": "ok",
                "allowed_city_ids": ["KR-47-130"],
                "verified_festival_cities": [
                    {
                        "city_id": "KR-47-130",
                        "city_name": "경주시",
                        "ddb_pk": "CITY#GYEONGJU",
                        "festivals": [
                            {
                                "festival_id": "F-GJ",
                                "name": "경주 전통 축제",
                                "city_id": "KR-47-130",
                                "theme_tags": ["축제·이벤트"],
                                "event_start_date": "2026-10-01",
                                "event_end_date": "2026-10-05",
                                "date_status": "confirmed",
                            },
                        ],
                    },
                ],
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

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    audit = cast(dict[str, object], pool["audit"])
    assert [call["city_id"] for call in search.calls] == ["KR-47-130", "KR-47-130"]
    assert audit["festival_seed_count"] == 1
