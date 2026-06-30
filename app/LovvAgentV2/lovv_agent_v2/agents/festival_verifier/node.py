"""Festival Verifier Node."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.festival_verifier.verifier import build_festival_gate_result
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.infra.aws_clients import create_boto3_client_factory
from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool, FestivalSeedResult
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


def festival_verifier_node(state: UnifiedAgentState) -> dict[str, Any]:
    """Optional node to verify theme matching of current local festivals."""
    intent = _mapping_payload(state.get("intent"), "state.intent")
    city_input_payload = _mapping_payload(
        intent.get("city_select_input"),
        "intent.city_select_input",
    )
    city_input = CitySelectInput.from_mapping(city_input_payload)
    if not city_input.include_festivals:
        return {
            "festival_gate": {
                "result": None,
                "allowed_city_ids": [],
                "clarification": None,
                "audit": {"skipped": True, "reason": "include_festivals_false"},
            },
            "routing": {
                "needs_clarification": False,
                "clarification_reason_code": None,
                "next_node": "city_select",
            },
        }

    candidates = _festival_candidates(state)
    if candidates:
        result = build_festival_gate_result(
            include_festivals=True,
            travel_month=city_input.travel_month,
            target_year=city_input.travel_year,
            requested_destination_id=city_input.destination_id,
            candidates=candidates,
        )
        return _gate_state_from_result(result.to_dict(), result.clarification)

    seed_result = _build_festival_lookup_tool().search_festival_city_seeds(
        country=city_input.country,
        travel_month=city_input.travel_month,
        travel_year=city_input.travel_year,
        theme_pool=city_input.active_required_themes,
        city_id=city_input.destination_id,
        city_key=_city_key(city_input_payload),
        max_candidates=None,
    )
    return _gate_state_from_seed_result(seed_result, city_input)


def _gate_state_from_result(
    result_payload: dict[str, Any],
    clarification_source: Any,
) -> dict[str, Any]:
    clarification = (
        None if clarification_source is None else clarification_source.to_dict()
    )
    needs_clarification = result_payload["status"] == "needs_clarification"
    return {
        "festival_gate": {
            "result": result_payload,
            "allowed_city_ids": list(result_payload["allowed_city_ids"]),
            "clarification": clarification,
            "audit": result_payload["audit"],
        },
        "routing": {
            "needs_clarification": needs_clarification,
            "clarification_reason_code": (
                None
                if clarification_source is None
                else clarification_source.reason_code
            ),
            "next_node": "response_packager" if needs_clarification else "city_select",
        },
        "memory": {"pending_clarification": clarification},
    }


def _gate_state_from_seed_result(
    seed_result: FestivalSeedResult,
    city_input: CitySelectInput,
) -> dict[str, Any]:
    result_payload = {
        "status": seed_result.status,
        "execution_mode": (
            "anchored" if city_input.destination_id is not None else "discovery"
        ),
        "tier": seed_result.tier,
        "allowed_city_ids": list(seed_result.allowed_city_ids),
        "verified_festival_cities": list(seed_result.verified_festival_cities),
        "clarification": seed_result.clarification,
        "audit": seed_result.audit,
        "candidates": [candidate.to_dict() for candidate in seed_result.candidates],
    }
    needs_clarification = seed_result.status == "needs_clarification"
    reason_code = _clarification_reason_code(seed_result.clarification)
    return {
        "festival_gate": {
            "result": result_payload,
            "allowed_city_ids": list(seed_result.allowed_city_ids),
            "clarification": seed_result.clarification,
            "audit": seed_result.audit,
        },
        "routing": {
            "needs_clarification": needs_clarification,
            "clarification_reason_code": reason_code,
            "next_node": "response_packager" if needs_clarification else "city_select",
        },
        "memory": {"pending_clarification": seed_result.clarification},
    }


def _build_festival_lookup_tool() -> DynamoLookupTool:
    config = RuntimeConfig.from_env()
    client_factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    dynamodb_client = client_factory("dynamodb", region_name=config.aws.region)
    return DynamoLookupTool(
        dynamodb=DynamoDbRepository(
            client=dynamodb_client,
            settings=config.dynamodb,
        ),
        search_budget=config.search_budget,
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


def _clarification_reason_code(clarification: Mapping[str, Any] | None) -> str | None:
    if clarification is None:
        return None
    reason_code = clarification.get("reason_code")
    return reason_code if isinstance(reason_code, str) and reason_code.strip() else None


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
