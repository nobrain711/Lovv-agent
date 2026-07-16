from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def current_order(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    request_key = _request_order_key(request)
    if request_key is not None:
        value = request.get(request_key)
        if not _empty_sequence(value):
            order = _mapping_sequence(value)
            if order is None or not all(_valid_order_item(item) for item in order):
                return ()
            return order
    for value in (
        state.get("currentOrder", state.get("current_order")),
        _planner_current_order(state),
        _response_current_order(state),
    ):
        order = _mapping_sequence(value)
        if order and all(_valid_order_item(item) for item in order):
            return order
    return ()


def current_order_for_city(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    request_key = _request_order_key(request)
    if request_key is not None:
        value = request.get(request_key)
        if not _empty_sequence(value):
            order = _mapping_sequence(value)
            return () if order is None else order
    for value in (
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


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    items: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        canonical = _canonical_order_item(item)
        if canonical is None:
            return None
        items.append(canonical)
    return tuple(items)


def _valid_order_item(item: Mapping[str, Any]) -> bool:
    content_id = item.get("contentId")
    day = item.get("day")
    order = item.get("order")
    return (
        isinstance(content_id, str)
        and bool(content_id.strip())
        and isinstance(day, int)
        and not isinstance(day, bool)
        and day > 0
        and isinstance(order, int)
        and not isinstance(order, bool)
        and order > 0
    )


def _canonical_order_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    content_id = _optional_text(_content_id(item))
    city_id = _optional_text(item.get("cityId", item.get("city_id")))
    if content_id is None and city_id is None:
        return None
    result: dict[str, Any] = {
        "itemId": _optional_text(item.get("itemId", item.get("item_id"))),
        "contentId": content_id,
        "itemType": _optional_text(item.get("itemType", item.get("item_type")))
        or _item_type(item),
        "day": _positive_int(item.get("day")),
        "order": _positive_int(item.get("order")),
        "title": _optional_text(item.get("title", item.get("name"))),
        "body": _optional_text(item.get("body")),
        "reason": _optional_text(item.get("reason")),
        "isSeed": _is_seed(item),
        "cityId": city_id,
        "theme": _optional_text(_theme(item)),
        "latitude": _optional_number(item.get("latitude")),
        "longitude": _optional_number(item.get("longitude")),
        "timeOfDay": _optional_text(item.get("timeOfDay", item.get("slot"))),
        "moveMinutes": _optional_number(item.get("moveMinutes", item.get("move_minutes"))),
    }
    exposure = item.get("indoorOutdoor", item.get("indoor_outdoor"))
    if isinstance(exposure, str) and exposure in {"indoor", "outdoor", "mixed", "unknown"}:
        result["indoorOutdoor"] = exposure
    return result


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


def _request_order_key(request: Mapping[str, Any]) -> str | None:
    if "currentOrder" in request:
        return "currentOrder"
    if "current_order" in request:
        return "current_order"
    return None


def _empty_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and not value


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _optional_number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["current_order", "current_order_for_city"]
