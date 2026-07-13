from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.festival_verifier.audit import build_festival_audit
from lovv_agent_v2.agents.festival_verifier.clarification_options import (
    anchor_conflict_clarification,
    festival_none_clarification,
    festival_tentative_clarification,
)
from lovv_agent_v2.agents.festival_verifier.date_policy import (
    DATE_STATUSES,
    candidate_matches_month,
    derive_date_status,
    month_number,
    positive_int,
)
from lovv_agent_v2.agents.festival_verifier.gate_result import (
    GATE_STATUSES,
    GATE_TIERS,
    FestivalGateResult,
    FestivalStatusCandidate,
)
from lovv_agent_v2.agents.festival_verifier.payloads import (
    unique_city_ids,
    verified_city_payloads,
)
from lovv_agent_v2.agents.festival_verifier.theme_policy import (
    candidate_matches_requested_theme,
    specific_theme_tokens,
)
from lovv_agent_v2.models.clarification import Clarification
from lovv_agent_v2.models.schemas import SchemaValidationError

def build_festival_gate_result(
    *,
    include_festivals: bool,
    travel_month: int,
    target_year: int | None,
    candidates: Sequence[Mapping[str, Any]],
    theme_pool: Sequence[str] = (),
    requested_destination_id: str | None = None,
) -> FestivalGateResult:
    if not include_festivals:
        raise SchemaValidationError("festival gate only runs when include_festivals is true")
    normalized_month = month_number(travel_month)
    normalized_year = positive_int(target_year, "target_year") if target_year else None
    requested_city = _optional_text(requested_destination_id)
    execution_mode = "anchored" if requested_city is not None else "discovery"
    status_candidates = tuple(
        _status_candidate(candidate, travel_month=normalized_month, target_year=normalized_year)
        for candidate in candidates
    )
    filtered = tuple(
        candidate
        for candidate in status_candidates
        if candidate_matches_month(candidate.payload, normalized_month)
    )
    theme_matched = _theme_matched_candidates(
        filtered,
        requested_themes=specific_theme_tokens(theme_pool),
    )
    confirmed = tuple(item for item in theme_matched if item.date_status == "confirmed")
    tentative = tuple(item for item in theme_matched if item.date_status == "tentative")
    excluded = tuple(
        item
        for item in filtered
        if item.date_status in {"outdated", "unknown", "skipped"}
    )
    audit = build_festival_audit(
        travel_month=normalized_month,
        target_year=normalized_year,
        requested_destination_id=requested_city,
        confirmed=confirmed,
        tentative=tentative,
        excluded=excluded,
    )
    if requested_city is not None:
        return _anchored_result(
            requested_city=requested_city,
            confirmed=confirmed,
            tentative=tentative,
            audit=audit,
        )
    return _discovery_result(confirmed=confirmed, tentative=tentative, audit=audit)


def _discovery_result(
    *,
    confirmed: Sequence[FestivalStatusCandidate],
    tentative: Sequence[FestivalStatusCandidate],
    audit: dict[str, Any],
) -> FestivalGateResult:
    if confirmed:
        return _ok_result(
            execution_mode="discovery",
            tier="confirmed",
            candidates=confirmed,
            audit=audit,
        )
    if tentative:
        clarification = festival_tentative_clarification(tentative, audit)
        return _clarification_result(
            execution_mode="discovery",
            tier="tentative",
            candidates=tentative,
            clarification=clarification,
            audit=audit,
        )
    clarification = festival_none_clarification(audit)
    return _clarification_result(
        execution_mode="discovery",
        tier="none",
        candidates=(),
        clarification=clarification,
        audit=audit,
    )


def _anchored_result(
    *,
    requested_city: str,
    confirmed: Sequence[FestivalStatusCandidate],
    tentative: Sequence[FestivalStatusCandidate],
    audit: dict[str, Any],
) -> FestivalGateResult:
    anchor_confirmed = tuple(item for item in confirmed if item.city_id == requested_city)
    if anchor_confirmed:
        return _ok_result(
            execution_mode="anchored",
            tier="confirmed",
            candidates=anchor_confirmed,
            audit=audit,
        )
    anchor_tentative = tuple(item for item in tentative if item.city_id == requested_city)
    if anchor_tentative:
        clarification = festival_tentative_clarification(anchor_tentative, audit)
        return _clarification_result(
            execution_mode="anchored",
            tier="tentative",
            candidates=anchor_tentative,
            clarification=clarification,
            audit=audit,
        )
    clarification = anchor_conflict_clarification(
        requested_city=requested_city,
        confirmed=confirmed,
        audit=audit,
    )
    return _clarification_result(
        execution_mode="anchored",
        tier="none",
        candidates=(),
        clarification=clarification,
        audit=audit,
    )


def _ok_result(
    *,
    execution_mode: str,
    tier: str,
    candidates: Sequence[FestivalStatusCandidate],
    audit: dict[str, Any],
) -> FestivalGateResult:
    allowed_city_ids = unique_city_ids(candidates)
    return FestivalGateResult(
        status="ok",
        execution_mode=execution_mode,
        tier=tier,
        allowed_city_ids=allowed_city_ids,
        verified_festival_cities=verified_city_payloads(candidates),
        clarification=None,
        audit=audit,
        candidates=tuple(item.payload for item in candidates),
    )


def _clarification_result(
    *,
    execution_mode: str,
    tier: str,
    candidates: Sequence[FestivalStatusCandidate],
    clarification: Clarification,
    audit: dict[str, Any],
) -> FestivalGateResult:
    return FestivalGateResult(
        status="needs_clarification",
        execution_mode=execution_mode,
        tier=tier,
        allowed_city_ids=(),
        verified_festival_cities=(),
        clarification=clarification,
        audit=audit,
        candidates=tuple(item.payload for item in candidates),
    )


def _status_candidate(
    candidate: Mapping[str, Any],
    *,
    travel_month: int,
    target_year: int | None,
) -> FestivalStatusCandidate:
    payload = dict(candidate)
    status = derive_date_status(
        payload,
        travel_month=travel_month,
        target_year=target_year,
    )
    payload["date_status"] = status
    return FestivalStatusCandidate(payload=payload, date_status=status)


def _theme_matched_candidates(
    candidates: Sequence[FestivalStatusCandidate],
    *,
    requested_themes: frozenset[str],
) -> tuple[FestivalStatusCandidate, ...]:
    if not requested_themes:
        return tuple(candidates)
    return tuple(
        candidate
        for candidate in candidates
        if candidate_matches_requested_theme(candidate.payload, requested_themes)
    )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "optional_text")


__all__ = [
    "DATE_STATUSES",
    "FestivalGateResult",
    "FestivalStatusCandidate",
    "GATE_STATUSES",
    "GATE_TIERS",
    "build_festival_gate_result",
]
