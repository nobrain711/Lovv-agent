from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.models.clarification import Clarification
from lovv_agent_v2.models.schemas import SchemaValidationError

GATE_STATUSES: tuple[str, ...] = ("ok", "needs_clarification")
GATE_TIERS: tuple[str, ...] = ("confirmed", "tentative", "none")


@dataclass(frozen=True, slots=True)
class FestivalStatusCandidate:
    payload: dict[str, Any]
    date_status: str

    @property
    def city_id(self) -> str:
        return _required_text(self.payload.get("city_id"), "city_id")

    @property
    def city_name(self) -> str:
        return _optional_text(self.payload.get("city_name")) or self.city_id

    @property
    def festival_id(self) -> str:
        return _required_text(self.payload.get("festival_id"), "festival_id")

    @property
    def festival_label(self) -> str:
        return _required_text(self.payload.get("name"), "name")


@dataclass(frozen=True, slots=True)
class FestivalGateResult:
    status: str
    execution_mode: str
    tier: str
    allowed_city_ids: tuple[str, ...]
    verified_festival_cities: tuple[dict[str, Any], ...]
    clarification: Clarification | None
    audit: dict[str, Any]
    candidates: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in GATE_STATUSES:
            raise SchemaValidationError("festival gate status is invalid")
        if self.tier not in GATE_TIERS:
            raise SchemaValidationError("festival gate tier is invalid")
        if self.status == "ok" and not self.allowed_city_ids:
            raise SchemaValidationError("ok festival gate requires allowed_city_ids")
        if self.status == "needs_clarification" and self.clarification is None:
            raise SchemaValidationError("festival clarification is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "execution_mode": self.execution_mode,
            "tier": self.tier,
            "allowed_city_ids": list(self.allowed_city_ids),
            "verified_festival_cities": list(self.verified_festival_cities),
            "clarification": (
                None if self.clarification is None else self.clarification.to_dict()
            ),
            "audit": self.audit,
            "candidates": list(self.candidates),
        }


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
    "FestivalGateResult",
    "FestivalStatusCandidate",
    "GATE_STATUSES",
    "GATE_TIERS",
]
