from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type SqlValue = JsonValue | Decimal | date | datetime
type SqlParameters = Mapping[str, SqlValue]
type SqlRow = Mapping[str, SqlValue]

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_safe_identifier(identifier: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")


def bounded_limit(value: int, max_limit: int) -> int:
    if value < 1:
        return 1
    return min(value, max_limit)


def positive_int(value: SqlValue | None, default: int) -> int:
    match value:
        case bool() | None:
            return default
        case int():
            return value if value > 0 else default
        case Decimal():
            integer = int(value)
            return integer if integer > 0 else default
        case str():
            return int(value) if value.isdecimal() and int(value) > 0 else default
        case _:
            return default


def text(value: SqlValue | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def empty_signals() -> dict[str, JsonValue]:
    return {
        "source": "rds_mysql_saved_itinerary_signals_tool",
        "saved_trip_count": 0,
        "recent_itineraries": [],
        "liked_itineraries": [],
    }


def itinerary_ids(*row_groups: Sequence[SqlRow]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for row_group in row_groups:
        for row in row_group:
            itinerary_id = text(row.get("id"))
            if itinerary_id is not None and itinerary_id not in seen:
                seen.add(itinerary_id)
                result.append(itinerary_id)
    return tuple(result)


def evidence_itinerary(
    row: SqlRow,
    items_by_itinerary: Mapping[str, tuple[dict[str, JsonValue], ...]],
    *,
    reaction: str | None,
) -> dict[str, JsonValue]:
    itinerary_id = text(row.get("id")) or ""
    item_rows = items_by_itinerary.get(itinerary_id, ())
    items = list(item_rows) if item_rows else items_from_snapshot(row.get("itinerary_json"))
    payload: dict[str, JsonValue] = {
        "itinerary_id": itinerary_id,
        "destination_json": json_mapping(row.get("destination_json")),
        "themes_json": json_list(row.get("themes_json")),
        "preference_snapshot": json_mapping(row.get("preference_snapshot")),
        "trip_type": text(row.get("trip_type")),
        "duration_label": text(row.get("duration_label")),
        "conditions_snapshot_json": json_mapping(row.get("conditions_snapshot_json")),
        "items": json_array_from_mappings(items),
    }
    if reaction is not None:
        payload["reaction"] = reaction
    return payload


def item_from_row(row: SqlRow) -> dict[str, JsonValue]:
    return {
        "place_name": text(row.get("place_name")),
        "content_id": text(row.get("content_id")),
        "place_id": text(row.get("place_id")),
        "day_index": positive_int(row.get("day_index"), 1),
        "sort_order": positive_int(row.get("sort_order"), 1),
    }


def items_from_snapshot(value: SqlValue | None) -> list[dict[str, JsonValue]]:
    snapshot = json_mapping(value)
    days = snapshot.get("days")
    if not isinstance(days, list):
        return []

    result: list[dict[str, JsonValue]] = []
    for day_position, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            continue
        day_index = positive_int(day.get("day") or day.get("dayIndex"), day_position)
        entries = day.get("items") or day.get("stops") or []
        if not isinstance(entries, list):
            continue
        for entry_position, entry in enumerate(entries, start=1):
            if isinstance(entry, dict):
                item = snapshot_item(entry, day_index=day_index, sort_order=entry_position)
                if item["place_name"] is not None:
                    result.append(item)
    return result


def snapshot_item(
    entry: Mapping[str, JsonValue],
    *,
    day_index: int,
    sort_order: int,
) -> dict[str, JsonValue]:
    return {
        "place_name": text(entry.get("place_name") or entry.get("placeName") or entry.get("title")),
        "content_id": text(entry.get("content_id") or entry.get("contentId")),
        "place_id": text(entry.get("place_id") or entry.get("placeId")),
        "day_index": day_index,
        "sort_order": positive_int(entry.get("sort_order") or entry.get("sortOrder"), sort_order),
    }


def json_mapping(value: SqlValue | None) -> dict[str, JsonValue]:
    parsed = json_value(value)
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: SqlValue | None) -> list[JsonValue]:
    parsed = json_value(value)
    return parsed if isinstance(parsed, list) else []


def json_array_from_mappings(items: Sequence[Mapping[str, JsonValue]]) -> list[JsonValue]:
    result: list[JsonValue] = []
    for item in items:
        result.append(dict(item))
    return result


def json_value(value: SqlValue | None) -> JsonValue:
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return coerce_json_value(loaded)
    if isinstance(value, bytes):
        try:
            loaded = json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return coerce_json_value(loaded)
    return coerce_json_value(value)


def coerce_json_value(value: object) -> JsonValue:
    match value:
        case None | bool() | int() | float() | str():
            return value
        case list():
            return [coerce_json_value(item) for item in value]
        case dict():
            return {
                key: coerce_json_value(item)
                for key, item in value.items()
                if isinstance(key, str)
            }
        case Decimal():
            return int(value) if value == value.to_integral_value() else float(value)
        case date() | datetime():
            return value.isoformat()
        case _:
            return None


__all__ = [
    "JsonValue",
    "SqlParameters",
    "SqlRow",
    "SqlValue",
    "bounded_limit",
    "empty_signals",
    "evidence_itinerary",
    "item_from_row",
    "itinerary_ids",
    "positive_int",
    "require_safe_identifier",
    "text",
]
