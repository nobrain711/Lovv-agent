from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from lovv_agent_v2.agents.planner.agent import (
    PlannerAgent,
    PlannerAgentRequest,
    PlannerAgentTools,
)
from lovv_agent_v2.agents.planner.state_adapter import (
    assemble_itinerary_step,
    retrieve_places,
    route_days_step,
)
from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.agents.planner.external.ors_provider import OrsProviderConfig, OrsTravelTimeProvider
from lovv_agent_v2.agents.planner.state.context import travel_time_provider
from lovv_agent_v2.agents.planner.external.travel_time import (
    MatrixResponse,
    SnapResponse,
    TravelTimeProvider,
)


def _place(
    place_id: str,
    title: str,
    sim: float,
    theme: str,
    *,
    lat: float | None = 38.2,
    lon: float | None = 128.6,
    soft_sim: float | None = None,
    subtype: str = "view",
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": [theme],
        "assigned_theme": theme,
        "subtype": subtype,
        "latitude": lat,
        "longitude": lon,
        "score_audit": {"score_components": {"raw_similarity": sim}},
        "soft_similarity": soft_sim if soft_sim is not None else sim,
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
                _place("raw-1", "해변", 0.92, "바다·해안", subtype="beach"),
                _place("raw-2", "등대", 0.86, "바다·해안", subtype="view"),
            )
        return (
            _place("soft-1", "조용한 향교", 0.20, "역사·문화", soft_sim=0.82, subtype="history"),
        )


@dataclass(frozen=True, slots=True)
class FakePlannerTools:
    destination_search: FakeDestinationSearch
    embedding: FakeEmbedding


class FakeTravelTimeProvider(TravelTimeProvider):
    def snap_places(self, places: object, transport_pref: str) -> SnapResponse:
        del transport_pref
        source_places = cast(tuple[dict[str, object], ...], tuple(places))
        return SnapResponse(
            places=source_places,
            excluded_place_ids=("missing-coords",),
            audit={"snap_provider": "fake", "snap_profile": "driving"},
        )

    def matrix_minutes(self, place_ids: tuple[str, ...], transport_pref: str) -> MatrixResponse:
        del transport_pref
        durations: dict[tuple[str, str], float] = {}
        for first in place_ids:
            for second in place_ids:
                durations[(first, second)] = 0.0 if first == second else 12.0
        for place_id in place_ids:
            if place_id != "far-leg":
                durations[(place_id, "far-leg")] = 90.0
                durations[("far-leg", place_id)] = 90.0
        return MatrixResponse(
            durations=durations,
            audit={"matrix_provider": "fake", "duration_unit": "minutes"},
        )


def test_planner_agent_core_uses_injected_tools_without_state_scratch() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    tools = PlannerAgentTools(
        runtime=FakePlannerTools(destination_search=search, embedding=embedding),
        travel_time_provider=FakeTravelTimeProvider(),
    )
    request = PlannerAgentRequest(
        selected_city={
            "city_id": "KR-SOKCHO",
            "city_name_ko": "속초",
            "ddb_pk": "CITY#SOKCHO",
        },
        city_id="KR-SOKCHO",
        ddb_pk="CITY#SOKCHO",
        raw_query="속초 바다 역사",
        soft_query="조용한 역사 산책",
        seeds=({"place_id": "raw-1", "theme": "바다·해안", "must_include": True},),
        active_themes=("바다·해안", "역사·문화"),
        theme_weights={"바다·해안": 0.7, "역사·문화": 0.3},
        trip_type="2d1n",
        transport_pref="car",
        min_count=3,
        target_count=6,
    )

    result = PlannerAgent(tools).run(request)

    assert embedding.queries == ["속초 바다 역사", "조용한 역사 산책"]
    assert [call["top_k"] for call in search.calls] == [50, 50]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO", "KR-SOKCHO"]
    assert result.place_pool["raw_places"]
    assert result.selection["places"]
    assert result.route["days"]


def _base_state() -> dict[str, object]:
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
            "city_selection_result": {
                "selected_city": {
                    "city_id": "KR-SOKCHO",
                    "city_name_ko": "속초",
                    "country": "KR",
                    "ddb_pk": "CITY#SOKCHO",
                },
                "alternative_city": {"city_id": "KR-GANGNEUNG", "city_name_ko": "강릉", "ddb_pk": "CITY#GANGNEUNG"},
                "seeds": [{"place_id": "raw-1", "theme": "바다·해안", "must_include": True}],
            },
        },
    }


def _set_planner_scratch(state: dict[str, object], **scratch: object) -> None:
    state["planner"] = {"scratch": scratch}


def test_retrieve_places_node_runs_city_anchored_raw_and_soft_channels() -> None:
    search = FakeDestinationSearch()
    embedding = FakeEmbedding()
    state = _base_state()
    _set_planner_scratch(
        state,
        runtime=FakePlannerTools(destination_search=search, embedding=embedding),
    )

    result = retrieve_places(state)

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    pool = cast(dict[str, object], scratch["place_pool"])
    assert embedding.queries == ["속초 바다 역사", "조용한 역사 산책"]
    assert [call["top_k"] for call in search.calls] == [50, 50]
    assert [call["theme"] for call in search.calls] == [None, None]
    assert [call["city_id"] for call in search.calls] == ["KR-SOKCHO", "KR-SOKCHO"]
    assert [call["ddb_pk"] for call in search.calls] == [None, None]
    assert [place["place_id"] for place in cast(tuple[dict[str, object], ...], pool["raw_places"])] == [
        "raw-1",
        "raw-2",
    ]
    assert [place["place_id"] for place in cast(tuple[dict[str, object], ...], pool["soft_places"])] == [
        "soft-1",
    ]


def test_planner_subgraph_preserves_internal_state_between_nodes() -> None:
    state = _base_state()
    _set_planner_scratch(
        state,
        runtime=FakePlannerTools(
            destination_search=FakeDestinationSearch(),
            embedding=FakeEmbedding(),
        ),
        travel_time_provider=FakeTravelTimeProvider(),
    )

    result = compile_planner_subgraph().invoke(state)

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    output = cast(dict[str, object], planner["planner_output"])
    assert output["itinerary"]
    assert "place_pool" in scratch
    assert "planner_place_pool" not in result


def test_route_days_node_uses_snap_matrix_and_excludes_only_unroutable() -> None:
    state = _base_state()
    _set_planner_scratch(
        state,
        runtime=FakePlannerTools(
            destination_search=FakeDestinationSearch(),
            embedding=FakeEmbedding(),
        ),
        travel_time_provider=FakeTravelTimeProvider(),
        place_pool={
            "raw_places": (
                _place("raw-1", "해변", 0.92, "바다·해안", subtype="beach"),
                _place("raw-2", "등대", 0.88, "바다·해안", subtype="view"),
                _place("soft-1", "향교", 0.74, "역사·문화", subtype="history"),
                _place("missing-coords", "좌표없음", 0.70, "역사·문화", lat=None, lon=None),
                _place("far-leg", "먼 전망대", 0.68, "바다·해안"),
            ),
            "soft_places": (),
        },
    )

    result = route_days_step(state)

    planner = cast(dict[str, object], result["planner"])
    scratch = cast(dict[str, object], planner["scratch"])
    routed = cast(dict[str, object], scratch["route"])
    audit = cast(dict[str, object], routed["audit"])
    assert audit["duration_unit"] == "minutes"
    assert audit["matrix_provider"] == "fake"
    assert "missing-coords" in cast(tuple[str, ...], audit["unroutable_place_ids"])
    assert audit["day_limit_min"] == 180.0
    assert audit["trim_floor_policy"] == "preserve_min_day_place_targets"


def test_assemble_itinerary_node_returns_structured_audit_and_thin_city_notice() -> None:
    state = _base_state()
    _set_planner_scratch(
        state,
        route={
            "days": (
                {
                    "day": 1,
                    "anchor_place_id": "raw-1",
                    "anchor_type": "seed",
                    "places": (
                        {
                            "place": _place("raw-1", "해변", 0.92, "바다·해안"),
                            "move_min_from_prev": 0,
                        },
                    ),
                    "day_travel_min": 0,
                },
            ),
            "reserve": (),
            "audit": {"duration_unit": "minutes", "trimmed_place_ids": ()},
        },
        selection={"audit": {"target_count": 8, "selected_count": 1}},
    )

    result = assemble_itinerary_step(state)

    output = cast(dict[str, object], cast(dict[str, object], result["planner"])["planner_output"])
    validation = cast(dict[str, object], output["validation_result"])
    structure = cast(dict[str, object], validation["itinerary_structure"])
    assert validation["planner_status_gate"] == "insufficient_candidates"
    assert validation["alternative_city_recommended"] == "KR-GANGNEUNG"
    assert structure["days"]
    assert "planner_audit" in validation


def test_assemble_itinerary_node_preserves_public_grounding_fields() -> None:
    state = _base_state()
    _set_planner_scratch(
        state,
        route={
            "days": (
                {
                    "day": 1,
                    "anchor_place_id": "raw-1",
                    "anchor_type": "seed",
                    "places": (
                        {
                            "place": {
                                **_place("raw-1", "해변", 0.92, "바다·해안"),
                                "city_id": "KR-SOKCHO",
                                "city_name_ko": "속초",
                                "ddb_pk": "CITY#SOKCHO",
                                "ddb_sk": "PLACE#RAW-1",
                                "source": "s3_vector",
                            },
                            "move_min_from_prev": 0,
                        },
                    ),
                    "day_travel_min": 0,
                },
            ),
            "reserve": (),
            "audit": {"duration_unit": "minutes", "trimmed_place_ids": ()},
        },
        selection={"audit": {"target_count": 4, "selected_count": 1}},
    )

    result = assemble_itinerary_step(state)

    output = cast(dict[str, object], cast(dict[str, object], result["planner"])["planner_output"])
    item = cast(tuple[dict[str, object], ...], output["itinerary"])[0]
    assert item["item_type"] == "attraction"
    assert item["city_id"] == "KR-SOKCHO"
    assert item["city_name_ko"] == "속초"
    assert item["theme_tags"] == ("바다·해안",)
    assert item["ddb_pk"] == "CITY#SOKCHO"
    assert item["ddb_sk"] == "PLACE#RAW-1"


def test_assemble_itinerary_node_labels_overnight_edge_day_slots() -> None:
    state = _base_state()
    _set_planner_scratch(
        state,
        route={
            "days": (
                {
                    "day": 1,
                    "anchor_place_id": "day1-a",
                    "anchor_type": "medoid",
                    "places": (
                        {"place": _place("day1-a", "첫날 오후", 0.92, "바다·해안"), "move_min_from_prev": 0},
                        {"place": _place("day1-b", "첫날 저녁", 0.88, "바다·해안"), "move_min_from_prev": 10},
                    ),
                    "day_travel_min": 10,
                },
                {
                    "day": 2,
                    "anchor_place_id": "day2-a",
                    "anchor_type": "medoid",
                    "places": (
                        {"place": _place("day2-a", "마지막날 오전", 0.86, "바다·해안"), "move_min_from_prev": 0},
                        {"place": _place("day2-b", "마지막날 오후", 0.82, "바다·해안"), "move_min_from_prev": 12},
                    ),
                    "day_travel_min": 12,
                },
            ),
            "reserve": (),
            "audit": {"duration_unit": "minutes", "trimmed_place_ids": ()},
        },
        selection={"audit": {"target_count": 6, "selected_count": 4}},
    )

    result = assemble_itinerary_step(state)

    output = cast(dict[str, object], cast(dict[str, object], result["planner"])["planner_output"])
    itinerary = cast(tuple[dict[str, object], ...], output["itinerary"])
    assert [item["slot"] for item in itinerary] == ["afternoon", "evening", "morning", "afternoon"]


def test_ors_provider_loads_external_snap_matrix_module(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module_file = tmp_path / "ors_matrix.py"
    module_file.write_text(
        "\n".join(
            (
                "class PlaceCandidate:",
                "    def __init__(self, place_id, title, lat, lon, theme_tags=None, subtype=None, source_tier=None):",
                "        self.place_id = place_id",
                "        self.title = title",
                "        self.lat = lat",
                "        self.lon = lon",
                "        self.theme_tags = theme_tags",
                "        self.subtype = subtype",
                "        self.source_tier = source_tier",
                "",
                "class SnapResult:",
                "    def __init__(self, profile, original_places, snapped_places):",
                "        self.profile = profile",
                "        self.original_places = original_places",
                "        self.snapped_places = snapped_places",
                "        self.snapped_distances_m = [3.5 for _ in original_places]",
                "        self.road_names = ['road' for _ in original_places]",
                "        self.snapped = [True for _ in original_places]",
                "        self.fallback_used = False",
                "",
                "class MatrixResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.place_ids = [place.place_id for place in places]",
                "        self.durations_sec = [[0.0 if a == b else 120.0 for b in self.place_ids] for a in self.place_ids]",
                "        self.fallback_used = False",
                "        self.source = 'ors'",
                "",
                "class OrsMatrixClient:",
                "    def __init__(self, timeout_sec=20, cache_dir=None):",
                "        self.timeout_sec = timeout_sec",
                "        self.cache_dir = cache_dir",
                "",
                "    def snap_places(self, places, profile, radius_m=300):",
                "        snapped = [PlaceCandidate(place.place_id, place.title, place.lat + 0.01, place.lon + 0.01) for place in places]",
                "        return SnapResult(profile, places, snapped)",
                "",
                "    def get_matrix(self, places, profile, use_cache=True, allow_fallback=True):",
                "        return MatrixResult(profile, places)",
                "",
            ),
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORS_API_KEY", "fake")
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=module_file, cache_dir=None, load_env_local=False),
    )

    snapped = provider.snap_places(
        (_place("raw-1", "해변", 0.92, "바다·해안"), _place("raw-2", "등대", 0.88, "바다·해안")),
        "walk",
    )
    matrix = provider.matrix_minutes(("raw-1", "raw-2"), "walk")

    assert snapped.audit["snap_provider"] == "ors_external"
    assert snapped.places[0]["latitude"] == 38.21
    assert matrix.audit["matrix_provider"] == "ors_external"
    assert matrix.durations[("raw-1", "raw-2")] == 2.0

    monkeypatch.setenv("LOVV_PLANNER_TRAVEL_TIME_PROVIDER", "ors")
    monkeypatch.setenv("LOVV_ORS_CODE_DIR", str(tmp_path))
    configured_provider = travel_time_provider({})

    assert isinstance(configured_provider, OrsTravelTimeProvider)
