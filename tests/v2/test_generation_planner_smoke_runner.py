from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _load_runner_module() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "run_generation_to_planner_smoke.py"
    spec = importlib.util.spec_from_file_location("run_generation_to_planner_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_initial_state_wraps_generation_intent_output() -> None:
    runner = _load_runner_module()
    state = runner.build_initial_state(
        {
            "id": "case-1",
            "intent_output": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "include_festivals": False,
                "cleaned_raw_query": "조용한 바다",
                "congestion_pref": "quiet",
                "transport_pref": "walk",
                "destination_id": None,
                "user_location": None,
            },
        },
    )

    assert state["request"]["request_id"] == "case-1"
    assert state["request"]["themes"] == ("바다·해안",)
    assert state["request"]["raw_query"] == "조용한 바다"
    assert "intent" not in state


def test_build_initial_state_accepts_mock_profile_record() -> None:
    runner = _load_runner_module()
    state = runner.build_initial_state(
        {
            "id": "case-1",
            "intent_output": {
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "active_required_themes": ["바다·해안"],
                "include_festivals": False,
                "cleaned_raw_query": "조용한 바다",
                "destination_id": None,
                "user_location": None,
            },
        },
        profile_record={"profile_id": "P05_three_trips_sea_threshold"},
    )

    assert state["profile"]["profile_record"]["profile_id"] == "P05_three_trips_sea_threshold"


def test_invoke_harness_uses_smoke_thread_id() -> None:
    runner = _load_runner_module()
    harness = RecordingHarness()
    state = {"request": {"request_id": "case-1"}}

    result = runner.invoke_harness(harness, state, case_id="case-1")

    assert result == {"ok": True}
    assert harness.payloads == [state]
    assert harness.configs == [{"configurable": {"thread_id": "v2-smoke:case-1"}}]


def test_build_smoke_harness_can_use_mock_contract_nodes(monkeypatch: Any) -> None:
    runner = _load_runner_module()
    monkeypatch.setattr(runner, "build_live_harness", lambda: "live")
    monkeypatch.setattr(runner, "build_mock_live_harness", lambda: "mock")

    assert runner.build_smoke_harness(use_mock_contract_nodes=True) == "mock"
    assert runner.build_smoke_harness(use_mock_contract_nodes=False) == "live"


def test_summarize_result_uses_interrupt_payload_as_response() -> None:
    runner = _load_runner_module()

    summary = runner.summarize_result(
        "case-wait",
        Path("case-wait.json"),
        {
            "__interrupt__": [
                SimpleNamespace(
                    value={
                        "clarification": {"reasonCode": "festival_none"},
                    },
                ),
            ],
            "festival_gate": {
                "result": {"status": "needs_clarification", "tier": "none"},
            },
        },
    )

    assert summary["response_status"] == "END_WAIT_USER"
    assert summary["response_payload"]["clarification"]["reasonCode"] == "festival_none"


class RecordingHarness:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.configs: list[dict[str, object]] = []

    def invoke(
        self,
        payload: dict[str, object],
        *,
        graph_config: dict[str, object],
    ) -> dict[str, object]:
        self.payloads.append(payload)
        self.configs.append(graph_config)
        return {"ok": True}
