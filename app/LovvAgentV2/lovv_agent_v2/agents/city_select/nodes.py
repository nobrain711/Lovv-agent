from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.retrieval.agent import (
    CitySelectRetrievalAgent,
    CitySelectRetrievalRequest,
)
from lovv_agent_v2.agents.city_select.scoring.agent import (
    CitySelectScoringAgent,
    CitySelectScoringRequest,
)
from lovv_agent_v2.tools.runtime_containers import CitySelectScoringTools, CitySelectTools
from lovv_agent_v2.tools.factories import (
    build_default_city_select_scoring_tools,
    build_default_city_select_tools,
)
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.models.schemas import SchemaValidationError


def retrieval_node(state: UnifiedAgentState) -> dict[str, dict[str, Any]]:
    candidate_input = _city_select_input_from_state(state)
    output = CitySelectRetrievalAgent(
        tools=_city_select_tools(state),
        tools_provider=build_default_city_select_tools,
    ).run(
        CitySelectRetrievalRequest(
            candidate_input=candidate_input,
            allowed_city_ids=_festival_gate_allowed_city_ids(state),
        ),
    )
    return {"city_select": output.city_select}


def scoring_and_selection_node(state: UnifiedAgentState) -> dict[str, dict[str, Any]]:
    city_select_state = (
        state.get("city_select", {})
        if isinstance(state, dict)
        else getattr(state, "city_select", {})
    )
    if not isinstance(city_select_state, Mapping):
        return {}
    return CitySelectScoringAgent(
        tools=_city_select_scoring_tools(state),
        tools_provider=build_default_city_select_scoring_tools,
    ).run(
        CitySelectScoringRequest(city_select_state=city_select_state),
    )


def _city_select_input_from_state(state: UnifiedAgentState) -> Mapping[str, Any]:
    intent = state.get("intent", {}) if isinstance(state, dict) else {}
    if not isinstance(intent, Mapping):
        raise SchemaValidationError("state.intent must be a mapping")
    candidate_input = intent.get("city_select_input")
    if not isinstance(candidate_input, Mapping):
        raise SchemaValidationError("city_select_input is required in state.intent")
    return candidate_input


def _festival_gate_allowed_city_ids(state: UnifiedAgentState) -> tuple[str, ...] | None:
    festival_gate = state.get("festival_gate", {}) if isinstance(state, dict) else {}
    if isinstance(festival_gate, Mapping):
        gate_allowed_city_ids = festival_gate.get("allowed_city_ids")
        if isinstance(gate_allowed_city_ids, Sequence) and not isinstance(
            gate_allowed_city_ids,
            (str, bytes),
        ):
            return tuple(str(city_id) for city_id in gate_allowed_city_ids)
    return None


def _city_select_tools(state: UnifiedAgentState) -> CitySelectTools | None:
    tools = runtime_value(state, "city_select_tools")
    return tools if isinstance(tools, CitySelectTools) else None


def _city_select_scoring_tools(state: UnifiedAgentState) -> CitySelectScoringTools | None:
    tools = runtime_value(state, "city_select_scoring_tools")
    return tools if isinstance(tools, CitySelectScoringTools) else None


__all__ = ["retrieval_node", "scoring_and_selection_node"]
