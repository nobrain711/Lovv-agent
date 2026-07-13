from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError


def candidate_value(candidate: Any, *field_names: str) -> Any:
    if isinstance(candidate, Mapping):
        for field_name in field_names:
            if field_name in candidate:
                return candidate[field_name]
        metadata = candidate.get("metadata")
        if isinstance(metadata, Mapping):
            return mapping_get(metadata, *field_names, default=None)
        return None
    for field_name in field_names:
        if hasattr(candidate, field_name):
            return getattr(candidate, field_name)
    metadata = getattr(candidate, "metadata", None)
    if isinstance(metadata, Mapping):
        return mapping_get(metadata, *field_names, default=None)
    return None


def place_id(candidate: Any) -> str:
    return required_text(
        candidate_value(candidate, "place_id", "placeId", "id", "key"),
        "place_id",
    )


def mapping_get(
    payload: Mapping[str, Any],
    *field_names: str,
    default: Any = None,
) -> Any:
    for field_name in field_names:
        if field_name in payload:
            return payload[field_name]
    return default


def string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(required_text(item, field_name) for item in value)


def required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional text must be a string")
    normalized = value.strip()
    return normalized or None


def positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return numeric(value, "value")


def round4(value: float) -> float:
    return round(value, 4)
