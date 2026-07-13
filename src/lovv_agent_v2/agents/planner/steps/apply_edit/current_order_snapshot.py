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
