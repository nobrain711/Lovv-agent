from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError

REASON_CODES: tuple[str, ...] = (
    "festival_none",
    "festival_tentative",
    "anchor_festival_conflict",
    "no_candidate_city",
    "contradiction",
    "thin_city",
    "weather_alternative_available",
    "modify_target_unresolved",
    "modify_target_ambiguous",
    "modify_ops_conflict",
    "modify_seed_theme_conflict",
)

NEXT_ACTIONS: tuple[str, ...] = (
    "anchor",
    "rerun_discovery",
    "abort",
    "weather_alternative",
)


@dataclass(frozen=True, slots=True)
class ClarificationApply:
    include_festivals: bool | None = None
    destination_id: str | None = None
    destination_label: str | None = None
    festival_id: str | None = None
    festival_label: str | None = None
    allow_tentative_festivals: bool | None = None
    accepted_festival_risk: bool | None = None
    travel_month: int | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ClarificationApply":
        return cls(
            include_festivals=_optional_bool(
                _first_optional(payload, "include_festivals", "includeFestivals"),
                "include_festivals",
            ),
            destination_id=_optional_text(
                _first_optional(payload, "destination_id", "destinationId"),
                "destination_id",
            ),
            destination_label=_optional_text(
                _first_optional(payload, "destination_label", "destinationLabel"),
                "destination_label",
            ),
            festival_id=_optional_text(
                _first_optional(payload, "festival_id", "festivalId"),
                "festival_id",
            ),
            festival_label=_optional_text(
                _first_optional(payload, "festival_label", "festivalLabel"),
                "festival_label",
            ),
            allow_tentative_festivals=_optional_bool(
                _first_optional(
                    payload,
                    "allow_tentative_festivals",
                    "allowTentativeFestivals",
                ),
                "allow_tentative_festivals",
            ),
            accepted_festival_risk=_optional_bool(
                _first_optional(
                    payload,
                    "accepted_festival_risk",
                    "acceptedFestivalRisk",
                ),
                "accepted_festival_risk",
            ),
            travel_month=_optional_int(
                _first_optional(payload, "travel_month", "travelMonth"),
                "travel_month",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_festivals": self.include_festivals,
            "destination_id": self.destination_id,
            "destination_label": self.destination_label,
            "festival_id": self.festival_id,
            "festival_label": self.festival_label,
            "allow_tentative_festivals": self.allow_tentative_festivals,
            "accepted_festival_risk": self.accepted_festival_risk,
            "travel_month": self.travel_month,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "includeFestivals": self.include_festivals,
            "destinationId": self.destination_id,
            "destinationLabel": self.destination_label,
            "festivalId": self.festival_id,
            "festivalLabel": self.festival_label,
            "allowTentativeFestivals": self.allow_tentative_festivals,
            "acceptedFestivalRisk": self.accepted_festival_risk,
            "travelMonth": self.travel_month,
        }


@dataclass(frozen=True, slots=True)
class ClarificationOption:
    option_id: str
    label: str
    apply: ClarificationApply
    then: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ClarificationOption":
        apply_payload = payload.get("apply")
        if not isinstance(apply_payload, Mapping):
            raise SchemaValidationError("clarification option.apply must be a mapping")
        return cls(
            option_id=_required_text(
                _first_present(payload, "option_id", "optionId"),
                "option_id",
            ),
            label=_required_text(_first_present(payload, "label"), "label"),
            apply=ClarificationApply.from_mapping(apply_payload),
            then=_required_text(_first_present(payload, "then"), "then"),
        )

    def __post_init__(self) -> None:
        if self.then not in NEXT_ACTIONS:
            raise SchemaValidationError("clarification option.then is invalid")
        if self.then == "anchor" and self.apply.destination_id is None:
            raise SchemaValidationError("anchor clarification option requires destination_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "label": self.label,
            "apply": self.apply.to_dict(),
            "then": self.then,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "optionId": self.option_id,
            "label": self.label,
            "apply": self.apply.to_public_dict(),
            "then": self.then,
        }


@dataclass(frozen=True, slots=True)
class Clarification:
    reason_code: str
    prompt: str
    options: tuple[ClarificationOption, ...]
    context: Mapping[str, Any] = field(default_factory=dict)
    failure_signals: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "Clarification":
        options = payload.get("options")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            raise SchemaValidationError("clarification.options must be a sequence")
        return cls(
            reason_code=_required_text(
                _first_present(payload, "reason_code", "reasonCode"),
                "reason_code",
            ),
            prompt=_required_text(_first_present(payload, "prompt"), "prompt"),
            options=tuple(
                ClarificationOption.from_mapping(_mapping(option, "clarification option"))
                for option in options
            ),
            context=_mapping(payload.get("context", {}), "clarification.context"),
            failure_signals=_string_tuple(
                _first_optional(payload, "failure_signals", "failureSignals") or (),
                "failure_signals",
            ),
        )

    def __post_init__(self) -> None:
        if self.reason_code not in REASON_CODES:
            raise SchemaValidationError("clarification reason_code is invalid")
        if not self.prompt.strip():
            raise SchemaValidationError("clarification prompt is required")
        if not self.options:
            raise SchemaValidationError("clarification options are required")
        if not isinstance(self.context, Mapping):
            raise SchemaValidationError("clarification context must be a mapping")
        if not isinstance(self.failure_signals, Sequence) or isinstance(
            self.failure_signals,
            (str, bytes),
        ):
            raise SchemaValidationError("clarification failure_signals must be a sequence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_clarification": True,
            "reason_code": self.reason_code,
            "prompt": self.prompt,
            "options": [option.to_dict() for option in self.options],
            "context": dict(self.context),
            "failure_signals": list(self.failure_signals),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "reasonCode": self.reason_code,
            "prompt": self.prompt,
            "options": [option.to_public_dict() for option in self.options],
            "context": dict(self.context),
            "failureSignals": list(self.failure_signals),
        }


__all__ = [
    "Clarification",
    "ClarificationApply",
    "ClarificationOption",
    "NEXT_ACTIONS",
    "REASON_CODES",
]


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    raise SchemaValidationError(f"missing required clarification field: {keys[0]}")


def _first_optional(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")
    return value


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SchemaValidationError(f"{field_name} must be a sequence")
    return tuple(_required_text(item, field_name) for item in value)
