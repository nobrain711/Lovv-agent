from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any


def _load_runner() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "run_retrieval_smoke_to_planner.py"
    spec = importlib.util.spec_from_file_location("run_retrieval_smoke_to_planner", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_planner_state_uses_selected_city_without_rescoring() -> None:
    runner = _load_runner()
    case = runner.SmokePlannerCase(
        case_id="case_daytrip",
        selected_ddb_pk="CITY#A",
        smoke=_smoke_case(),
        transport_pref="car",
    )

    state = runner.build_planner_state(case)

    selected = state["city_select"]["city_selection_result"]["selected_city"]
    assert selected["ddb_pk"] == "CITY#A"
    assert selected["city_id"] == "KR-A"
    runtime = state["planner"]["scratch"]["runtime"]
    assert runtime.destination_search.raw_candidates[0]["place_id"] == "a-1"
    assert all(candidate["ddb_pk"] == "CITY#A" for candidate in runtime.destination_search.raw_candidates)


def test_run_case_invokes_real_planner_subgraph() -> None:
    runner = _load_runner()
    result = runner.run_case(
        runner.SmokePlannerCase(
            case_id="case_daytrip",
            selected_ddb_pk="CITY#A",
            smoke=_smoke_case(),
            transport_pref="car",
        ),
    )

    output = result["planner"]["planner_output"]
    assert output["validation_result"]["planner_status_gate"] == "ok"
    assert len(output["itinerary"]) == 3
    assert {item["city_id"] for item in output["itinerary"]} == {"KR-A"}


def _smoke_case() -> dict[str, object]:
    return {
        "case_id": "case_daytrip",
        "query": {
            "raw_query": "조용한 바다",
            "soft_query": "한적한 바다",
            "themes": ["바다·해안"],
        },
        "channels": {
            "raw": {"no_theme": {"ranked": [_place("a-1", 0.10), _place("b-1", 0.08, ddb_pk="CITY#B"), _place("a-2", 0.12), _place("a-3", 0.14)]}},
            "soft": {"no_theme": {"ranked": [_place("a-2", 0.05), _place("a-4", 0.16)]}},
        },
    }


def _place(place_id: str, distance: float, *, ddb_pk: str = "CITY#A") -> dict[str, object]:
    return {
        "place_id": place_id,
        "distance": distance,
        "city_id": "KR-A" if ddb_pk == "CITY#A" else "KR-B",
        "city_name_ko": "도시A" if ddb_pk == "CITY#A" else "도시B",
        "title": f"장소 {place_id}",
        "theme_tags": ["바다·해안"],
        "ddb_pk": ddb_pk,
        "lat": 37.0 + distance,
        "lon": 127.0 + distance,
    }
