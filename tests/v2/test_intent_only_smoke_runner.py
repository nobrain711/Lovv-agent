from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path("scripts/v2/run_intent_only_smoke.py")


def test_generation_fixture_state_uses_front_request_shape() -> None:
    module = _load_runner()
    case = {
        "id": "sample-generation",
        "intent_output": {
            "country": "KR",
            "travel_month": 9,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["바다·해안"],
            "include_festivals": False,
            "cleaned_raw_query": "조용한 바다 여행을 원해요.",
            "soft_preference_query": "한적한 분위기.",
            "destination_id": None,
            "user_location": None,
        },
    }

    state = module.state_from_generation_case(case)

    assert state["request"]["entryType"] == "create"
    assert state["request"]["themes"] == ["바다·해안"]
    assert state["request"]["naturalLanguageQuery"] == "조용한 바다 여행을 원해요."
    assert state["request"]["softPreferenceQuery"] == "한적한 분위기."


def test_custom_cases_run_through_intent_node_without_live_runtime() -> None:
    module = _load_runner()

    results = [module.run_case(case, runtime=None) for case in module.custom_cases()]

    assert [result["case_id"] for result in results] == [
        "custom_create_history_quiet_walk",
        "custom_modify_multi_replace",
        "custom_modify_seed_conflict",
        "custom_clarify_festival_none",
        "custom_confirm_itinerary",
    ]
    assert results[1]["summary"]["edit_ops_count"] == 2
    assert results[2]["summary"]["status"] == "needs_clarification"
    assert "soft_preference_query" in results[0]["summary"]


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("run_intent_only_smoke", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
