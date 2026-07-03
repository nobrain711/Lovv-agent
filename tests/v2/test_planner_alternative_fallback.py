from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from lovv_agent_v2.agents.planner.node import planner_node
from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.agents.planner.external.travel_time import MatrixResponse, SnapResponse, TravelTimeProvider
from lovv_agent_v2.agents.planner.steps.retry_alternative_city.node import should_retry_alternative_city


def _place(place_id: str, title: str, sim: float, theme: str, subtype: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "subtype": subtype,
        "latitude": 38.2,
        "longitude": 128.6,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": sim,
    }


def _seed(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    city_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "place_id": place_id,
        "title": title,
        "theme": theme,
        "theme_tags": [theme],
        "sim": sim,
        "latitude": 38.2,
        "longitude": 128.6,
        "must_include": True,
    }
    if city_id is not None:
        payload["city_id"] = city_id
    return payload


class FakeEmbedding:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(self.queries)), 0.5]


class ThinThenAlternativeDestinationSearch:
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
            {"vector": query_vector, "top_k": top_k, "city_id": city_id, "ddb_pk": ddb_pk, "theme": theme},
        )
        if city_id == "KR-GANGNEUNG" and len(self.calls) % 2 == 1:
            return (
                _place("alt-1", "강릉 바다", 0.92, "바다·해안", "beach"),
                _place("alt-2", "강릉 항구", 0.88, "바다·해안", "port"),
                _place("alt-3", "강릉 역사", 0.84, "역사·문화", "history"),
                _place("alt-4", "강릉 산책", 0.80, "역사·문화", "walk"),
            )
        if city_id == "KR-SOKCHO" and len(self.calls) % 2 == 1:
            return (_place("thin-1", "속초 바다", 0.92, "바다·해안", "beach"),)
        return ()


@dataclass(frozen=True, slots=True)
class FakePlannerTools:
    destination_search: ThinThenAlternativeDestinationSearch
    embedding: FakeEmbedding


class FakeTravelTimeProvider(TravelTimeProvider):
    def snap_places(self, places: object, transport_pref: str) -> SnapResponse:
        del transport_pref
        source_places = cast(tuple[dict[str, object], ...], tuple(places))
        return SnapResponse(places=source_places, excluded_place_ids=(), audit={"snap_provider": "fake"})

    def matrix_minutes(self, place_ids: tuple[str, ...], transport_pref: str) -> MatrixResponse:
        del transport_pref
        durations = {
            (first, second): 0.0 if first == second else 12.0
            for first in place_ids
            for second in place_ids
        }
        return MatrixResponse(durations=durations, audit={"matrix_provider": "fake", "duration_unit": "minutes"})


def test_planner_subgraph_retries_second_city_when_primary_city_is_too_thin() -> None:
    search = ThinThenAlternativeDestinationSearch()
    result = compile_planner_subgraph().invoke(_state(search))

    _assert_retry_result(result, search)


def test_planner_node_does_not_retry_ranked_city_without_alternative_seeds() -> None:
    search = ThinThenAlternativeDestinationSearch()
    result = planner_node(_state(search, include_alternative=False))

    planner = cast(dict[str, object], result["planner"])
    output = cast(dict[str, object], planner["planner_output"])
    validation = cast(dict[str, object], output["validation_result"])
    assert validation["planner_status_gate"] == "insufficient_candidates"
    assert planner.get("fallback") is None


def test_planner_subgraph_reuses_second_city_scoring_audit_without_runtime() -> None:
    result = compile_planner_subgraph().invoke(_state_without_planner_runtime())

    planner = cast(dict[str, object], result["planner"])
    output = cast(dict[str, object], planner["planner_output"])
    validation = cast(dict[str, object], output["validation_result"])
    selected_city = cast(
        dict[str, object],
        cast(dict[str, object], cast(dict[str, object], result["city_select"])["city_selection_result"])[
            "selected_city"
        ],
    )
    fallback = cast(dict[str, object], planner["fallback"])
    itinerary = cast(list[dict[str, object]], output["itinerary"])
    assert validation["planner_status_gate"] == "ok"
    assert selected_city["city_id"] == "KR-51-170"
    assert fallback["from_city_id"] == "CITY#GANGJIN"
    assert fallback["to_city_id"] == "KR-51-170"
    assert len(itinerary) == 4
    assert {item["city_id"] for item in itinerary} == {"KR-51-170"}
    assert selected_city["province"] == "강원특별자치도"


def test_direct_anchor_without_city_select_does_not_retry_alternative_city() -> None:
    state = {
        "intent": {
            "city_select_input": {
                "destination_id": "KR-DONGHAE",
                "include_festivals": False,
            },
        },
        "request": {"include_festivals": False},
        "planner": {"validation_result": {"planner_status_gate": "insufficient_candidates"}},
    }

    assert not any(should_retry_alternative_city(item) for item in (state, {**state, "city_select": {}}))


def _state(
    search: ThinThenAlternativeDestinationSearch,
    *,
    include_alternative: bool = True,
) -> dict[str, object]:
    city_selection_result: dict[str, object] = {
        "selected_city": {
            "city_id": "KR-SOKCHO",
            "city_name_ko": "속초",
            "country": "KR",
            "ddb_pk": "CITY#SOKCHO",
        },
        "seeds": [{"place_id": "thin-1", "theme": "바다·해안", "must_include": True}],
    }
    if include_alternative:
        city_selection_result["alternative_city"] = {
            "city_name_ko": "강릉",
            "ddb_pk": "CITY#GANGNEUNG",
            "seeds": (
                _seed("alt-seed-1", "강릉 바다", 0.92, "바다·해안", city_id="KR-GANGNEUNG"),
                _seed("alt-seed-2", "강릉 역사", 0.84, "역사·문화", city_id="KR-GANGNEUNG"),
            ),
        }
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "속초 바다 역사",
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안", "역사·문화"],
                "theme_weights": {"바다·해안": 0.7, "역사·문화": 0.3},
                "transport_pref": "car",
                "soft_preference_query": "조용한 역사 산책",
            },
        },
        "city_select": {
            "city_selection_result": city_selection_result,
            "scoring_audit": {
                "city_rankings": (
                    {"city_id": "KR-SOKCHO", "city_name_ko": "속초", "city_score": 0.9},
                    {"city_id": "KR-GANGNEUNG", "city_name_ko": "강릉", "city_score": 0.8},
                ),
            },
        },
        "planner": {
            "scratch": {
                "runtime": FakePlannerTools(destination_search=search, embedding=FakeEmbedding()),
                "travel_time_provider": FakeTravelTimeProvider(),
            },
        },
    }


def _state_without_planner_runtime() -> dict[str, object]:
    return {
        "intent": {
            "city_select_input": {
                "cleaned_raw_query": "조용한 바다",
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "theme_weights": {"바다·해안": 1.0},
                "transport_pref": "car",
                "soft_preference_query": "",
            },
        },
        "city_select": {
            "city_selection_result": {
                "selected_city": {
                    "city_id": "CITY#GANGJIN",
                    "city_name_ko": "강진군",
                    "country": "KR",
                    "ddb_pk": "CITY#GANGJIN",
                    "province": "전라남도",
                },
                "alternative_city": {
                    "city_id": "CITY#DONGHAE",
                    "city_name_ko": "동해시",
                    "ddb_pk": "CITY#DONGHAE",
                    "seeds": (
                        _seed("alt-1", "동해 해변", 0.91, "바다·해안", city_id="KR-51-170"),
                        _seed("alt-2", "동해 항구", 0.88, "바다·해안", city_id="KR-51-170"),
                        _seed("alt-3", "동해 전망", 0.86, "바다·해안", city_id="KR-51-170"),
                        _seed("alt-4", "동해 산책", 0.82, "바다·해안", city_id="KR-51-170"),
                    ),
                },
                "seeds": [{"place_id": "thin-1", "theme": "바다·해안", "must_include": True}],
            },
            "scoring_audit": {
                "city_rankings": (
                    {"city_id": "CITY#GANGJIN", "city_name_ko": "강진군", "city_score": 0.9},
                    {"city_id": "CITY#DONGHAE", "city_name_ko": "동해시", "city_score": 0.8},
                ),
            },
        },
        "planner": {"scratch": {"travel_time_provider": FakeTravelTimeProvider()}},
    }


def _assert_retry_result(
    result: object,
    search: ThinThenAlternativeDestinationSearch,
) -> None:
    payload = cast(dict[str, object], result)
    planner = cast(dict[str, object], payload["planner"])
    output = cast(dict[str, object], planner["planner_output"])
    validation = cast(dict[str, object], output["validation_result"])
    city_select = cast(dict[str, object], payload["city_select"])
    city_result = cast(dict[str, object], city_select["city_selection_result"])
    selected_city = cast(dict[str, object], city_result["selected_city"])
    fallback = cast(dict[str, object], planner["fallback"])
    seeds = cast(tuple[dict[str, object], ...] | list[dict[str, object]], city_result["seeds"])
    assert validation["planner_status_gate"] == "ok"
    assert selected_city["city_id"] == "KR-GANGNEUNG"
    assert fallback["from_city_id"] == "KR-SOKCHO"
    assert fallback["to_city_id"] == "KR-GANGNEUNG"
    assert seeds
    assert seeds[0]["place_id"] != "thin-1"
    assert [call["city_id"] for call in search.calls] == [
        "KR-SOKCHO",
        "KR-SOKCHO",
        "KR-GANGNEUNG",
        "KR-GANGNEUNG",
    ]
