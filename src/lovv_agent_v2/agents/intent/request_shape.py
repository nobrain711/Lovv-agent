from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def entry_type(request: Mapping[str, Any]) -> str:
    value = request.get("entryType", request.get("entry_type", "create"))
    if not isinstance(value, str):
        return "create"
    normalized = value.strip().lower().replace("-", "_")
    match normalized:
        case "clarify":
            return "clarify"
        case "modify":
            return "modify"
        case "confirm":
            return "confirm"
        case "create" | "chat" | "":
            return "create"
        case _:
            return "create"


def has_create_request_fields(request: Mapping[str, Any]) -> bool:
    required_fields = ("country", "travelMonth", "tripType", "includeFestivals")
    snake_fields = ("country", "travel_month", "trip_type", "include_festivals")
    has_core = all(key in request for key in required_fields) or all(
        key in request for key in snake_fields
    )
    has_query = any(
        key in request
        for key in ("rawQuery", "raw_query", "naturalLanguageQuery")
    )
    return has_core and has_query


__all__ = ["entry_type", "has_create_request_fields"]
