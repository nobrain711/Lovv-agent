from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_itinerary_item_payload(
    item: Mapping[str, Any],
    sort_order: int,
) -> dict[str, Any]:
    return {
        "itemId": f"item-{sort_order}",
        "contentId": item.get("placeId") or item.get("festivalId"),
        "itemType": item.get("itemType") or item.get("item_type") or _item_type(item),
        "day": item.get("day"),
        "order": item.get("order"),
        "timeOfDay": item.get("slot"),
        "sortOrder": sort_order,
        "title": item.get("title"),
        "body": item.get("body"),
        "reason": item.get("reason"),
        "isSeed": (
            item.get("isSeed") is True
            or item.get("is_seed") is True
            or item.get("reason_code") == "seed_floor"
        ),
        "cityId": item.get("cityId") or item.get("city_id"),
        "theme": item.get("theme") or _first_theme(item.get("theme_tags")),
        "moveMinutes": _optional_number(item, "moveMinutes", "move_minutes"),
        "latitude": _optional_number(item, "latitude", "lat"),
        "longitude": _optional_number(item, "longitude", "lng", "lon"),
    }


def _item_type(item: Mapping[str, Any]) -> str:
    return "festival" if item.get("festivalId") is not None else "attraction"


def _first_theme(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        first = value[0]
        return first if isinstance(first, str) else None
    return None


def _optional_number(item: Mapping[str, Any], *field_names: str) -> float | int | None:
    for field_name in field_names:
        value = item.get(field_name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


__all__ = ["build_itinerary_item_payload"]
