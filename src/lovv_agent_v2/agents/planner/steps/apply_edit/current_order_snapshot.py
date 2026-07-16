from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def request_with_current_order(state: Mapping[str, Any]) -> dict[str, Any]:
    request = dict(_mapping(state.get("request")))
    planner = _mapping(state.get("planner"))
    output = _mapping(planner.get("planner_output"))
    current_items = tuple(
        _current_order_item(item)
        for item in sorted(
            output.get("itinerary", ()),
            key=lambda item: (_int(_mapping(item).get("day")), _int(_mapping(item).get("order"))),
        )
        if isinstance(item, Mapping)
    )
    if current_items:
        request["currentOrder"] = current_items
    return request


def merge_current_order_item(
    previous: Mapping[str, Any],
    item: Mapping[str, Any],
    content_id: str,
) -> dict[str, Any]:
    result = dict(previous)
    request_fields = {
        "day": item.get("day"),
        "order": item.get("order"),
        "slot": item.get("timeOfDay", item.get("slot")),
        "item_type": item.get("itemType", item.get("item_type")),
        "placeId": content_id,
        "title": item.get("title"),
        "body": item.get("body"),
        "reason": item.get("reason"),
        "moveMinutes": item.get("moveMinutes", item.get("move_minutes")),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "city_id": item.get("cityId", item.get("city_id")),
    }
    result.update({key: value for key, value in request_fields.items() if value is not None})
    exposure = item.get("indoorOutdoor", item.get("indoor_outdoor"))
    if isinstance(exposure, str) and exposure in {"indoor", "outdoor", "mixed", "unknown"}:
        result["indoor_outdoor"] = exposure
    theme = item.get("theme")
    if theme is not None:
        result["theme_tags"] = (theme,)
    if "isSeed" in item or "is_seed" in item:
        result["isSeed"] = item.get("isSeed", item.get("is_seed")) is True
    return result


def _current_order_item(item: Mapping[str, Any]) -> dict[str, Any]:
    theme_tags = item.get("theme_tags", ())
    theme = theme_tags[0] if isinstance(theme_tags, Sequence) and theme_tags else None
    return {
        "itemId": item.get("itemId", item.get("item_id")),
        "contentId": item.get("placeId", item.get("contentId", item.get("content_id"))),
        "itemType": item.get("item_type", item.get("itemType", "attraction")),
        "day": item.get("day"),
        "order": item.get("order"),
        "title": item.get("title"),
        "isSeed": item.get("isSeed") is True,
        "cityId": item.get("city_id", item.get("cityId")),
        "theme": theme if isinstance(theme, str) else None,
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "timeOfDay": item.get("slot", item.get("timeOfDay")),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["merge_current_order_item", "request_with_current_order"]
