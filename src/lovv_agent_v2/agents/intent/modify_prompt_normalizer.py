from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.intent.modify_replacement_query import (
    replacement_query_fields,
)
from lovv_agent_v2.agents.intent.modify_slots import (
    avoid_city_ids,
    current_order,
    public_operation,
    slot_replace_operations,
)
from lovv_agent_v2.agents.intent.parser import parse_initial_query
from lovv_agent_v2.models.city_identity import load_default_city_identity_map


def normalize_prompt_edit_ops(
    operations: list[Any],
    request: Mapping[str, Any],
) -> list[Any]:
    order_items = current_order(request, {})
    rule_operations = _rule_operations(request, order_items)
    if len(rule_operations) == len(operations) and rule_operations:
        return [public_operation(operation) for operation in rule_operations]
    return [
        _normalize_prompt_edit_op(operation, index=index, order_items=order_items)
        for index, operation in enumerate(operations, start=1)
    ]


def normalize_prompt_city_change(
    value: dict[str, Any] | None,
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if "target_city_id" in value and "target_city_name" in value:
        return value
    city_name = _optional_text(
        value.get("new_city", value.get("target_city", value.get("city"))),
    )
    city_map = load_default_city_identity_map()
    identity = city_map.get(city_name) if city_name else None
    if identity is None and city_name is not None:
        identity = city_map.get(f"{city_name}시")
    if identity is None:
        return value
    raw_query = _optional_text(
        request.get("rawModifyQuery", request.get("raw_modify_query")),
    )
    return {
        "target_city_id": identity.city_id,
        "target_city_name": identity.city_name_ko,
        "city_preference_query": raw_query,
        "carry_over_themes": True,
        "carry_over_festivals": True,
        "avoid_city_ids": avoid_city_ids(current_order(request, {})),
    }


def _normalize_prompt_edit_op(
    operation: Any,
    *,
    index: int,
    order_items: tuple[Mapping[str, Any], ...],
) -> Any:
    if not isinstance(operation, Mapping):
        return operation
    item = _matched_item(operation, order_items)
    raw_query = _replacement_phrase(operation)
    target = _target_payload(operation, item)
    content_id = target.get("content_id")
    condition = _condition(operation)
    return {
        "op_id": _optional_text(operation.get("op_id")) or f"op-{index}",
        "op": "REPLACE",
        "target": target,
        "condition": {
            **replacement_query_fields(raw_query),
            "theme": _optional_text(condition.get("theme")) or _theme(raw_query),
            "mood": _optional_text(condition.get("mood"))
            or ("quiet" if raw_query is not None and "조용" in raw_query else None),
            "place_type": _optional_text(condition.get("place_type")),
            "location": _optional_text(condition.get("location")),
            "avoid_content_ids": _avoid_content_ids(condition, content_id),
        },
        "seed_policy": _mapping_or_none(operation.get("seed_policy")) or _seed_policy(item),
    }


def _rule_operations(
    request: Mapping[str, Any],
    order_items: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    raw_query = _optional_text(
        request.get("rawModifyQuery", request.get("raw_modify_query")),
    )
    if raw_query is None:
        return ()
    operations = slot_replace_operations(raw_query, order_items)
    if any(operation["target"]["resolution"] != "exact" for operation in operations):
        return ()
    return operations


def _matched_item(
    operation: Mapping[str, Any],
    order_items: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any] | None:
    target = _target_source(operation)
    item_id = _optional_text(
        target.get("target_item_id", target.get("item_id", target.get("itemId"))),
    )
    day = _optional_int(target.get("target_day", target.get("day")))
    order = _optional_int(target.get("target_order", target.get("order")))
    for item in order_items:
        if item_id is not None and item_id == _optional_text(item.get("itemId", item.get("item_id"))):
            return item
        if day is not None and order is not None and day == item.get("day") and order == item.get("order"):
            return item
    return None


def _target_payload(
    operation: Mapping[str, Any],
    item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    target = _target_source(operation)
    source = item if item is not None else target
    day = _optional_int(target.get("target_day", target.get("day"))) or _optional_int(source.get("day"))
    order = _optional_int(target.get("target_order", target.get("order"))) or _optional_int(source.get("order"))
    return {
        "item_id": _optional_text(source.get("itemId", source.get("item_id", target.get("target_item_id")))),
        "content_id": _optional_text(source.get("contentId", source.get("content_id"))),
        "item_type": _optional_text(source.get("itemType", source.get("item_type"))),
        "day": day,
        "order": order,
        "target_text": _optional_text(source.get("title", source.get("target_text"))) or _target_text(day, order),
        "resolution": "exact",
    }


def _replacement_phrase(operation: Mapping[str, Any]) -> str | None:
    condition = _condition(operation)
    value = condition.get("replacement_query_raw", condition.get("replacement_query"))
    if value is not None:
        return _optional_text(value)
    return _optional_text(
        operation.get(
            "replacement_query",
            operation.get("new_content_description"),
        ),
    )


def _theme(raw_query: str | None) -> str | None:
    preference = parse_initial_query(raw_query or "")
    return preference.active_theme_labels[0] if preference.active_theme_labels else None


def _seed_policy(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if item is None or item.get("isSeed", item.get("is_seed")) is not True:
        return {"target_is_seed": False, "policy": "not_seed"}
    required_theme = _optional_text(item.get("theme"))
    policy: dict[str, Any] = {"target_is_seed": True, "policy": "same_theme_required"}
    if required_theme is not None:
        policy["required_theme"] = required_theme
    return policy


def _target_source(operation: Mapping[str, Any]) -> Mapping[str, Any]:
    target = operation.get("target")
    return target if isinstance(target, Mapping) else operation


def _condition(operation: Mapping[str, Any]) -> Mapping[str, Any]:
    condition = operation.get("condition")
    return condition if isinstance(condition, Mapping) else {}


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _avoid_content_ids(
    condition: Mapping[str, Any],
    content_id: Any,
) -> list[str]:
    value = condition.get("avoid_content_ids")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return [content_id] if isinstance(content_id, str) else []


def _target_text(day: int | None, order: int | None) -> str:
    if day is None or order is None:
        return "수정 대상 장소"
    return f"{day}일차 {order}번째 장소"


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


__all__ = ["normalize_prompt_city_change", "normalize_prompt_edit_ops"]
