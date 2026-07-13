from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def current_order(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    for value in (
        request.get("currentOrder", request.get("current_order")),
        state.get("currentOrder", state.get("current_order")),
        _planner_current_order(state),
        _response_current_order(state),
    ):
        order = _mapping_sequence(value)
        if order:
            return order
    return ()


def _planner_current_order(state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return ()
    planner_output = planner.get("planner_output")
    if not isinstance(planner_output, Mapping):
        return ()
    return _order_from_itinerary(planner_output.get("itinerary"))


def _response_current_order(state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    response = state.get("response")
    if not isinstance(response, Mapping):
        return ()
    payload = response.get("response_payload")
    if not isinstance(payload, Mapping):
        return ()
    itinerary = payload.get("itinerary")
    if not isinstance(itinerary, Mapping):
        return ()
    days = itinerary.get("days")
    if not isinstance(days, Sequence) or isinstance(days, (str, bytes)):
        return ()
    order: list[dict[str, Any]] = []
    for day_payload in days:
        if not isinstance(day_payload, Mapping):
            continue
        _extend_response_day_order(order, day_payload)
    return tuple(order)


def _extend_response_day_order(
    order: list[dict[str, Any]],
    day_payload: Mapping[str, Any],
) -> None:
    day = day_payload.get("day")
    items = day_payload.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return
    for index, item in enumerate(items, start=1):
        if isinstance(item, Mapping):
            order.append(_order_item(item, day, index))


def _order_from_itinerary(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    day_counts: dict[int, int] = {}
    order: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        day = _item_int(item, "day") or 1
        day_counts[day] = day_counts.get(day, 0) + 1
        order.append(_order_item(item, day, day_counts[day]))
    return tuple(order)


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _order_item(item: Mapping[str, Any], day: Any, order: int) -> dict[str, Any]:
    item_day = day if isinstance(day, int) else 1
    return {
        "itemId": item.get("itemId", item.get("item_id", f"item-{item_day}-{order}")),
        "contentId": _content_id(item),
        "itemType": item.get("itemType", item.get("item_type", _item_type(item))),
        "day": item_day,
        "order": item.get("order") if isinstance(item.get("order"), int) else order,
        "title": item.get("title", item.get("name")),
        "isSeed": _is_seed(item),
        "cityId": item.get("cityId", item.get("city_id")),
        "theme": _theme(item),
    }


def _content_id(item: Mapping[str, Any]) -> Any:
    return item.get(
        "contentId",
        item.get("content_id", item.get("placeId", item.get("festivalId"))),
    )


def _item_type(item: Mapping[str, Any]) -> str:
    return "festival" if item.get("festivalId") is not None else "attraction"


def _is_seed(item: Mapping[str, Any]) -> bool:
    return item.get("isSeed") is True or item.get("is_seed") is True or item.get("reason_code") == "seed_floor"


def _theme(item: Mapping[str, Any]) -> Any:
    theme = item.get("theme")
    if theme is not None:
        return theme
    tags = item.get("theme_tags")
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)) and tags:
        return tags[0]
    return None


def _item_int(item: Mapping[str, Any], field_name: str) -> int | None:
    value = item.get(field_name)
    if isinstance(value, int):
        return value
    return None


__all__ = ["current_order"]
