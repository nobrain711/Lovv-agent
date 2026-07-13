"""Festival Verifier Node."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.festival_verifier.agent import FestivalVerifierAgent
from lovv_agent_v2.agents.festival_verifier.contracts import FestivalVerifierInput
from lovv_agent_v2.tools.runtime_containers import FestivalVerifierTools
from lovv_agent_v2.tools.factories import build_festival_verifier_tools
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def festival_verifier_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Optional node to verify theme matching of current local festivals."""
    request = _festival_verifier_input(state)
    tools = _festival_verifier_tools(state) or build_festival_verifier_tools()
    return FestivalVerifierAgent(tools).run(request).to_state()


def _festival_verifier_input(state: UnifiedAgentState) -> FestivalVerifierInput:
    intent = _mapping_payload(state.get("intent"), "state.intent")
    city_input_payload = _mapping_payload(
        intent.get("city_select_input"),
        "intent.city_select_input",
    )
    city_input = CitySelectInput.from_mapping(city_input_payload)
    return FestivalVerifierInput(
        city_input=city_input,
        candidate_payloads=_festival_candidates(state),
        city_key=_city_key(city_input_payload),
    )


def _festival_candidates(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    festival_gate = state.get("festival_gate")
    if isinstance(festival_gate, Mapping) and "candidates" in festival_gate:
        return _mapping_sequence(festival_gate["candidates"], "festival_gate.candidates")
    request = state.get("request")
    if isinstance(request, Mapping) and "festival_candidates" in request:
        return _mapping_sequence(
            request["festival_candidates"],
            "request.festival_candidates",
        )
    return ()


def _city_key(city_input: Mapping[str, Any]) -> str | None:
    for key in (
        "city_key",
        "cityKey",
        "destination_city_key",
        "destinationCityKey",
        "ddb_pk",
        "ddbPk",
    ):
        value = city_input.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise SchemaValidationError(f"{key} must be a string")
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _mapping_payload(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be an object")
    return value


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaValidationError(f"{field_name} must be a list of objects")
    candidates: list[Mapping[str, Any]] = []
    for item in value:
        candidates.append(_mapping_payload(item, field_name))
    return tuple(candidates)


def _festival_verifier_tools(state: UnifiedAgentState) -> FestivalVerifierTools | None:
    tools = runtime_value(state, "festival_verifier_tools")
    return tools if isinstance(tools, FestivalVerifierTools) else None
