from __future__ import annotations

import inspect
from collections.abc import Sequence

from lovv_agent_v2.agents.festival_verifier import agent as festival_agent_module
from lovv_agent_v2.agents.festival_verifier import node as festival_node_module
from lovv_agent_v2.tools import runtime_containers as festival_tools_containers_module
from lovv_agent_v2.tools import factories as festival_tools_factories_module
from lovv_agent_v2.agents.festival_verifier.agent import FestivalVerifierAgent
from lovv_agent_v2.agents.festival_verifier.contracts import FestivalVerifierInput
from lovv_agent_v2.tools.runtime_containers import FestivalVerifierTools
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.infra.dynamo_lookup import FestivalSeedResult
from lovv_agent_v2.models.schemas import CitySelectInput


def _city_input() -> CitySelectInput:
    return CitySelectInput.from_mapping(
        {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["축제"],
            "include_festivals": True,
            "cleaned_raw_query": "10월 김해 축제",
            "soft_preference_query": "",
            "unsupported_conditions": [],
            "destination_id": "KR-36-4",
            "user_location": None,
            "execution_mode": "anchored_place_search",
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
        },
    )


def test_festival_agent_and_tools_do_not_import_unified_state() -> None:
    # Given: V2_30 requires agent/tool layers to be independent from LangGraph state.
    agent_source = inspect.getsource(festival_agent_module)
    tools_containers_source = inspect.getsource(festival_tools_containers_module)
    tools_factories_source = inspect.getsource(festival_tools_factories_module)

    # When/Then: neither layer imports the UnifiedAgentState boundary type.
    assert "UnifiedAgentState" not in agent_source
    assert "UnifiedAgentState" not in tools_containers_source
    assert "UnifiedAgentState" not in tools_factories_source


def test_festival_node_keeps_external_io_in_tools_layer() -> None:
    # Given: V2_30 allows SDK/runtime construction only through tools.
    node_source = inspect.getsource(festival_node_module)

    # When/Then: the node adapter imports no concrete AWS/Dynamo runtime boundary.
    assert "RuntimeConfig" not in node_source
    assert "DynamoLookupTool" not in node_source
    assert "DynamoDbRepository" not in node_source
    assert "create_boto3" not in node_source


def test_festival_agent_outputs_single_public_festival_gate_group() -> None:
    # Given: the agent has an anchored request and a lookup tool result.
    lookup = RecordingFestivalLookup()
    request = FestivalVerifierInput(
        city_input=_city_input(),
        candidate_payloads=(),
        city_key="CITY#GIMHAE",
    )

    # When: the application agent runs outside LangGraph.
    output = FestivalVerifierAgent(FestivalVerifierTools(festival_lookup=lookup)).run(
        request,
    )

    # Then: the state patch contains only festival_gate, with duplicate fields aligned.
    assert list(output.to_state()) == ["festival_gate"]
    festival_gate = output.festival_gate
    assert festival_gate["allowed_city_ids"] == ["KR-36-4"]
    assert festival_gate["allowed_city_ids"] == festival_gate["result"]["allowed_city_ids"]
    assert festival_gate["verified_festival_cities"] == festival_gate["result"]["verified_festival_cities"]
    assert festival_gate["audit"] == festival_gate["result"]["audit"]
    assert festival_gate["audit"]["ddb_pk_usage"] == {
        "preserve_for_diagnostics": True,
        "use_as_s3_vector_filter": False,
    }


def test_festival_node_uses_injected_runtime_tools(monkeypatch) -> None:
    def fail_default_tools() -> FestivalVerifierTools:
        raise AssertionError("default festival verifier tools should not be used")

    monkeypatch.setattr(festival_node_module, "build_festival_verifier_tools", fail_default_tools)

    result = festival_node_module.festival_verifier_node(
        {
            "intent": {"city_select_input": _city_input().to_dict()},
            "runtime": {
                "festival_verifier_tools": FestivalVerifierTools(
                    festival_lookup=RecordingFestivalLookup(),
                ),
            },
        },
    )

    assert result["festival_gate"]["allowed_city_ids"] == ["KR-36-4"]


def test_festival_node_uses_invocation_runtime_tools(monkeypatch) -> None:
    def fail_default_tools() -> FestivalVerifierTools:
        raise AssertionError("default festival verifier tools should not be used")

    monkeypatch.setattr(festival_node_module, "build_festival_verifier_tools", fail_default_tools)

    with invocation_runtime(
        {
            "festival_verifier_tools": FestivalVerifierTools(
                festival_lookup=RecordingFestivalLookup(),
            ),
        },
    ):
        result = festival_node_module.festival_verifier_node(
            {"intent": {"city_select_input": _city_input().to_dict()}},
        )

    assert result["festival_gate"]["allowed_city_ids"] == ["KR-36-4"]


class RecordingFestivalLookup:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        travel_year: int | None = None,
        theme_pool: Sequence[str],
        city_id: str | None = None,
        city_key: str | None = None,
        max_candidates: int | None = None,
    ) -> FestivalSeedResult:
        self.calls.append(
            {
                "country": country,
                "travel_month": travel_month,
                "travel_year": travel_year,
                "theme_pool": tuple(theme_pool),
                "city_id": city_id,
                "city_key": city_key,
                "max_candidates": max_candidates,
            },
        )
        return FestivalSeedResult(
            status="ok",
            tier="confirmed",
            allowed_city_ids=("KR-36-4",),
            verified_festival_cities=(
                {
                    "ddb_pk": "CITY#GIMHAE",
                    "city_id": "KR-36-4",
                    "city_name": "김해시",
                    "festivals": [
                        {
                            "festival_id": "F-GIMHAE",
                            "name": "김해 축제",
                            "city_id": "KR-36-4",
                            "SK": "FESTIVAL#F-GIMHAE",
                        },
                    ],
                },
            ),
            audit={
                "travel_month": 10,
                "target_year": 2026,
                "requested_destination_id": "KR-36-4",
                "candidate_counts": {
                    "confirmed": 1,
                    "tentative": 0,
                    "excluded": 0,
                },
            },
        )
