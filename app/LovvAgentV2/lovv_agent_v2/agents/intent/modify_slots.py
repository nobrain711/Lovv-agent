from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from lovv_agent_v2.agents.intent.modify_replacement_query import (
    replacement_query_fields,
    slot_replacement_phrase,
)
from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.intent.parser import parse_initial_query

ORDER_TOKEN_RE: Final = r"(?:\d+\s*번째|첫\s*번째?|두\s*번째?|세\s*번째?|네\s*번째?|마지막)"
ORDER_LIST_RE: Final = rf"{ORDER_TOKEN_RE}(?:\s*(?:,|와|과|랑|하고|및)\s*{ORDER_TOKEN_RE})+"


def slot_replace_operation(
    raw_query: str,
    current_order: tuple[Mapping[str, Any], ...],
) -> dict[str, Any] | None:
    matches = _target_matches(raw_query, current_order)
    if not matches:
        return None
    if len(matches) > 1:
        first = _operation_for_item(raw_query, matches[0])
        first["target"]["resolution"] = "ambiguous"
        first["clarification_options"] = [_target_option(item) for item in matches]
        return first
    return _operation_for_item(raw_query, matches[0])


def slot_replace_operations(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    same_day_operations = _same_day_multi_target_operations(raw_query, current_order_items)
    if same_day_operations is not None:
        return same_day_operations
    segments = _targeted_segments(raw_query)
    if len(segments) <= 1:
        operation = slot_replace_operation(raw_query, current_order_items)
        return () if operation is None else (operation,)
    operations: list[dict[str, Any]] = []
    for segment in segments:
        operation = slot_replace_operation(segment, current_order_items)
        if operation is None:
            return ()
        if operation["target"]["resolution"] == "ambiguous":
            return (operation,)
        operations.append(_operation_with_id(operation, len(operations) + 1))
    return tuple(operations)


def public_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "op_id": operation["op_id"],
        "op": operation["op"],
        "target": operation["target"],
        "condition": operation["condition"],
        "seed_policy": operation["seed_policy"],
    }


def _operation_with_id(operation: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        **operation,
        "op_id": f"op-{index}",
    }


def _targeted_segments(raw_query: str) -> tuple[str, ...]:
    matches = tuple(re.finditer(rf"\d+일차\s*(?:오전|오후|{ORDER_TOKEN_RE})", raw_query))
    if len(matches) <= 1:
        return (raw_query,)
    return tuple(
        raw_query[match.start() : matches[index + 1].start()].strip(" .,。")
        if index + 1 < len(matches)
        else raw_query[match.start() :].strip(" .,。")
        for index, match in enumerate(matches)
    )


def _same_day_multi_target_operations(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], ...] | None:
    match = re.search(
        rf"(?P<day>\d+)일차\s*(?P<orders>{ORDER_LIST_RE})\s*(?:장소|코스|일정)?",
        raw_query,
    )
    if match is None:
        return None
    day = int(match.group("day"))
    tail = raw_query[match.end() :].strip(" .,。")
    operations: list[dict[str, Any]] = []
    for order in _order_tokens(match.group("orders"), current_order_items, day):
        item = _item_at(current_order_items, day, order)
        if item is None:
            return ()
        operation_query = f"{day}일차 {order}번째 장소 {tail}".strip()
        operations.append(
            _operation_with_id(_operation_for_item(operation_query, item), len(operations) + 1),
        )
    return tuple(operations)


def avoid_city_ids(current_order_items: tuple[Mapping[str, Any], ...]) -> list[str]:
    city_ids: list[str] = []
    for item in current_order_items:
        city_id = _optional_text(item.get("cityId", item.get("city_id")))
        if city_id is not None and city_id not in city_ids:
            city_ids.append(city_id)
    return city_ids


def _target_matches(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    title_matches: list[Mapping[str, Any]] = []
    for item in current_order_items:
        title = _item_title(item)
        if title is not None and title in raw_query:
            title_matches.append(item)
    if title_matches:
        return tuple(title_matches)
    day = _query_int(raw_query, r"(\d+)일차")
    order = _query_order(raw_query, current_order_items, day)
    if day is None or order is None:
        return ()
    item = _item_at(current_order_items, day, order)
    return () if item is None else (item,)


def _operation_for_item(raw_query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    target = {
        "item_id": _optional_text(item.get("itemId", item.get("item_id"))),
        "content_id": _optional_text(item.get("contentId", item.get("content_id"))),
        "item_type": _optional_text(item.get("itemType", item.get("item_type"))),
        "day": _item_int(item, "day"),
        "order": _item_int(item, "order"),
        "target_text": _target_text(raw_query, item),
        "resolution": "exact",
    }
    replacement_query = _replacement_query(raw_query, item)
    query_fields = replacement_query_fields(replacement_query)
    preference = parse_initial_query(replacement_query or "")
    theme = preference.active_theme_labels[0] if preference.active_theme_labels else None
    content_id = target["content_id"]
    return {
        "op_id": "op-1",
        "op": "REPLACE",
        "target": target,
        "condition": {
            **query_fields,
            "theme": theme,
            "mood": "quiet" if "조용" in raw_query else None,
            "place_type": "walk" if "산책" in raw_query else None,
            "location": None,
            "avoid_content_ids": [content_id] if content_id is not None else [],
        },
        "seed_policy": _seed_policy(item, theme),
    }


def _seed_policy(item: Mapping[str, Any], replacement_theme: str | None) -> dict[str, Any]:
    target_is_seed = item.get("isSeed", item.get("is_seed")) is True
    if not target_is_seed:
        return {"target_is_seed": False, "policy": "not_seed"}
    required_theme = _optional_text(item.get("theme"))
    if replacement_theme is not None and replacement_theme != required_theme:
        return {"target_is_seed": True, "policy": "seed_theme_conflict"}
    policy: dict[str, Any] = {"target_is_seed": True, "policy": "same_theme_required"}
    if required_theme is not None:
        policy["required_theme"] = required_theme
    return policy


def _target_option(item: Mapping[str, Any]) -> dict[str, Any]:
    item_id = _optional_text(item.get("itemId", item.get("item_id"))) or ""
    day = _item_int(item, "day")
    order = _item_int(item, "order")
    return {
        "option_id": f"target:{item_id}",
        "label": f"{day}일차 {order}번째 장소",
        "apply": {"target_item_id": item_id},
    }


def _replacement_query(raw_query: str, item: Mapping[str, Any]) -> str | None:
    return slot_replacement_phrase(raw_query, item, order_token_re=ORDER_TOKEN_RE)


def _target_text(raw_query: str, item: Mapping[str, Any]) -> str:
    title = _item_title(item)
    if title is not None and title in raw_query:
        return title
    day = _item_int(item, "day")
    order = _item_int(item, "order")
    return f"{day}일차 {order}번째 장소"


def _query_order(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
    day: int | None,
) -> int | None:
    if "오전" in raw_query or "첫" in raw_query:
        return 1
    if "오후" in raw_query or "점심 전" in raw_query or "두" in raw_query:
        return 2
    korean_order = _korean_order(raw_query)
    if isinstance(korean_order, int):
        return korean_order
    if korean_order == "last" and day is not None:
        return _last_order(current_order_items, day)
    return _query_int(raw_query, r"(\d+)번째")


def _order_tokens(
    raw_orders: str,
    current_order_items: tuple[Mapping[str, Any], ...],
    day: int,
) -> tuple[int, ...]:
    orders: list[int] = []
    for match in re.finditer(ORDER_TOKEN_RE, raw_orders):
        order = _query_order(match.group(0), current_order_items, day)
        if order is not None and order not in orders:
            orders.append(order)
    return tuple(orders)


def _korean_order(raw_query: str) -> int | str | None:
    if "세" in raw_query:
        return 3
    if "네" in raw_query:
        return 4
    if "마지막" in raw_query:
        return "last"
    return None


def _last_order(
    current_order_items: tuple[Mapping[str, Any], ...],
    day: int,
) -> int | None:
    orders = [
        order
        for item in current_order_items
        if _item_int(item, "day") == day and (order := _item_int(item, "order")) is not None
    ]
    return max(orders) if orders else None


def _item_at(
    current_order_items: tuple[Mapping[str, Any], ...],
    day: int,
    order: int,
) -> Mapping[str, Any] | None:
    for item in current_order_items:
        if _item_int(item, "day") == day and _item_int(item, "order") == order:
            return item
    return None


def _query_int(raw_query: str, pattern: str) -> int | None:
    match = re.search(pattern, raw_query)
    if match is None:
        return None
    return int(match.group(1))


def _item_title(item: Mapping[str, Any]) -> str | None:
    return _optional_text(item.get("title", item.get("name")))


def _item_int(item: Mapping[str, Any], field_name: str) -> int | None:
    value = item.get(field_name)
    if isinstance(value, int):
        return value
    return None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
