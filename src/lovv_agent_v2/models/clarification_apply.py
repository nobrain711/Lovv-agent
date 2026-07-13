from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError


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
    active_required_themes: tuple[str, ...] | None = None
    disliked_city_ids: tuple[str, ...] | None = None
    festival_theme_agnostic: bool | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ClarificationApply":
        return cls(
            include_festivals=_optional_bool(_first(payload, "include_festivals", "includeFestivals"), "include_festivals"),
            destination_id=_optional_text(_first(payload, "destination_id", "destinationId"), "destination_id"),
            destination_label=_optional_text(_first(payload, "destination_label", "destinationLabel"), "destination_label"),
            festival_id=_optional_text(_first(payload, "festival_id", "festivalId"), "festival_id"),
            festival_label=_optional_text(_first(payload, "festival_label", "festivalLabel"), "festival_label"),
            allow_tentative_festivals=_optional_bool(_first(payload, "allow_tentative_festivals", "allowTentativeFestivals"), "allow_tentative_festivals"),
            accepted_festival_risk=_optional_bool(_first(payload, "accepted_festival_risk", "acceptedFestivalRisk"), "accepted_festival_risk"),
            travel_month=_optional_int(_first(payload, "travel_month", "travelMonth"), "travel_month"),
            active_required_themes=_optional_string_tuple(_first(payload, "active_required_themes", "activeRequiredThemes"), "active_required_themes"),
            disliked_city_ids=_optional_string_tuple(_first(payload, "disliked_city_ids", "dislikedCityIds"), "disliked_city_ids"),
            festival_theme_agnostic=_optional_bool(_first(payload, "festival_theme_agnostic", "festivalThemeAgnostic"), "festival_theme_agnostic"),
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
            "active_required_themes": self.active_required_themes,
            "disliked_city_ids": self.disliked_city_ids,
            "festival_theme_agnostic": self.festival_theme_agnostic,
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
            "activeRequiredThemes": (
                list(self.active_required_themes)
                if self.active_required_themes is not None
                else None
            ),
            "dislikedCityIds": (
                list(self.disliked_city_ids)
                if self.disliked_city_ids is not None
                else None
            ),
            "festivalThemeAgnostic": self.festival_theme_agnostic,
        }


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


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


def _optional_string_tuple(value: Any, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SchemaValidationError(f"{field_name} must be a sequence")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = ["ClarificationApply"]
