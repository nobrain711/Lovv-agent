from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.festival_verifier.contracts import (
    FestivalVerifierInput,
    FestivalVerifierOutput,
)
from lovv_agent_v2.tools.runtime_containers import FestivalVerifierTools
from lovv_agent_v2.agents.festival_verifier.verifier import build_festival_gate_result
from lovv_agent_v2.infra.dynamo_lookup import FestivalSeedResult
from lovv_agent_v2.models.schemas import CitySelectInput, SchemaValidationError


@dataclass(frozen=True, slots=True)
class FestivalVerifierAgent:
    tools: FestivalVerifierTools

    def run(self, request: FestivalVerifierInput) -> FestivalVerifierOutput:
        city_input = request.city_input
        if not city_input.include_festivals:
            return FestivalVerifierOutput(
                festival_gate=_festival_gate_payload(
                    None,
                    audit={"skipped": True, "reason": "include_festivals_false"},
                ),
            )
        if request.candidate_payloads:
            return FestivalVerifierOutput(
                festival_gate=_festival_gate_payload(
                    _preloaded_result_payload(
                        city_input=city_input,
                        candidates=request.candidate_payloads,
                    ),
                ),
            )
        seed_result = self.tools.festival_lookup.search_festival_city_seeds(
            country=city_input.country,
            travel_month=city_input.travel_month,
            travel_year=city_input.travel_year,
            theme_pool=city_input.active_required_themes,
            city_id=city_input.destination_id,
            city_key=request.city_key,
            max_candidates=None,
        )
        return FestivalVerifierOutput(
            festival_gate=_festival_gate_payload(
                _seed_result_payload(seed_result=seed_result, city_input=city_input),
            ),
        )


def _preloaded_result_payload(
    *,
    city_input: CitySelectInput,
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result = build_festival_gate_result(
        include_festivals=True,
        travel_month=city_input.travel_month,
        target_year=city_input.travel_year,
        theme_pool=city_input.active_required_themes,
        requested_destination_id=city_input.destination_id,
        candidates=candidates,
    )
    return result.to_dict()


def _seed_result_payload(
    *,
    seed_result: FestivalSeedResult,
    city_input: CitySelectInput,
) -> dict[str, Any]:
    return {
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


def _festival_gate_payload(
    result_payload: Mapping[str, Any] | None,
    *,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if result_payload is None:
        return {
            "result": None,
            "allowed_city_ids": [],
            "verified_festival_cities": [],
            "clarification": None,
            "audit": _audit_payload(audit or {}),
        }
    result = dict(result_payload)
    allowed_city_ids = _list_payload(
        result.get("allowed_city_ids"),
        "festival_gate.result.allowed_city_ids",
    )
    verified_festival_cities = _list_payload(
        result.get("verified_festival_cities"),
        "festival_gate.result.verified_festival_cities",
    )
    clarification = _optional_mapping_payload(
        result.get("clarification"),
        "festival_gate.result.clarification",
    )
    gate_audit = _audit_payload(
        _mapping_payload(result.get("audit"), "festival_gate.result.audit"),
    )
    result["allowed_city_ids"] = allowed_city_ids
    result["verified_festival_cities"] = verified_festival_cities
    result["clarification"] = clarification
    result["audit"] = gate_audit
    return {
        "result": result,
        "allowed_city_ids": allowed_city_ids,
        "verified_festival_cities": verified_festival_cities,
        "clarification": clarification,
        "audit": gate_audit,
    }


def _audit_payload(audit: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(audit)
    payload["ddb_pk_usage"] = {
        "preserve_for_diagnostics": True,
        "use_as_s3_vector_filter": False,
    }
    return payload


def _optional_mapping_payload(
    value: Any,
    field_name: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(_mapping_payload(value, field_name))


def _list_payload(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaValidationError(f"{field_name} must be a list")
    return list(value)


def _mapping_payload(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be an object")
    return value


__all__ = ["FestivalVerifierAgent"]
