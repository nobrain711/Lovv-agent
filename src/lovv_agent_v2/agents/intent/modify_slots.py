from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.modify_replacement_query import (
    replacement_query_fields,
)
from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.intent.parser import parse_initial_query


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
    matches = tuple(re.finditer(r"\d+일차\s*(?:오전|오후|\d+번째)", raw_query))
    if len(matches) <= 1:
        return (raw_query,)
    return tuple(
        raw_query[match.start() : matches[index + 1].start()].strip(" .,。")
        if index + 1 < len(matches)
        else raw_query[match.start() :].strip(" .,。")
        for index, match in enumerate(matches)
    )


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
    order = _query_order(raw_query)
    if day is None or order is None:
        return ()
    return tuple(
        item
        for item in current_order_items
        if _item_int(item, "day") == day and _item_int(item, "order") == order
    )


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
    if "말고" not in raw_query:
        return _replacement_query_without_negative_target(raw_query, item)
    _, replacement = raw_query.split("말고", 1)
    normalized = replacement.strip(" .,。")
    normalized = re.sub(
        r"(쪽으로|으로|로)?\s*(바꾸고|바꿔줘|바꿔|변경해줘|교체해줘)\.?$",
        "",
        normalized,
    )
    normalized = normalized.strip(" .,。")
    return normalized or None


def _replacement_query_without_negative_target(
    raw_query: str,
    item: Mapping[str, Any],
) -> str | None:
    normalized = re.sub(
        r"^\s*\d+일차\s*(오전|오후|\d+번째)?\s*(장소|코스|일정)?\s*(은|는|을|를|만)?\s*",
        "",
        raw_query,
    )
    normalized = re.sub(
        r"(쪽으로|으로|로)?\s*(바꾸고|바꿔줘|바꿔|변경해줘|교체해줘)\.?$",
        "",
        normalized.strip(" .,。"),
    )
    title = _item_title(item)
    if title is not None:
        normalized = re.sub(
            rf"^\s*{re.escape(title)}\s*(은|는|을|를|만)?\s*",
            "",
            normalized,
        )
    normalized = normalized.strip(" .,。")
    if normalized in {"다른 곳", "다른 장소", "다른 코스"}:
        return None
    return normalized or None


def _target_text(raw_query: str, item: Mapping[str, Any]) -> str:
    title = _item_title(item)
    if title is not None and title in raw_query:
        return title
    day = _item_int(item, "day")
    order = _item_int(item, "order")
    return f"{day}일차 {order}번째 장소"


def _query_order(raw_query: str) -> int | None:
    if "오전" in raw_query or "첫" in raw_query:
        return 1
    if "오후" in raw_query or "점심 전" in raw_query:
        return 2
    return _query_int(raw_query, r"(\d+)번째")


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
