from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.intent.modify_replacement_query import replacement_query_fields
from lovv_agent_v2.agents.intent.parser import parse_initial_query


def day_regenerate_request(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
) -> dict[str, Any] | None:
    if not _is_day_regenerate_query(raw_query):
        return None
    day = _target_day(raw_query, current_order_items)
    if day is None or not any(_item_int(item, "day") == day for item in current_order_items):
        return None
    return {
        "day": day,
        "condition": _condition(raw_query, current_order_items, day),
    }


def normalize_prompt_day_regenerate(
    value: Any,
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return day_regenerate_request(_raw_query(request) or "", _current_order(request))
    raw_query = _raw_query(request)
    current_items = _current_order(request)
    day = _optional_int(value.get("day", value.get("target_day")))
    if day is None and raw_query is not None:
        day = _target_day(raw_query, current_items)
    if day is None:
        return None
    query = _optional_text(
        value.get("replacement_query_raw", value.get("replacement_query")),
    )
    if query is None and raw_query is not None:
        query = _day_replacement_query(raw_query)
    return {"day": day, "condition": _condition(query or "", current_items, day)}


def _condition(
    raw_query: str | None,
    current_order_items: tuple[Mapping[str, Any], ...],
    day: int,
) -> dict[str, Any]:
    replacement_query = _day_replacement_query(raw_query or "")
    query_fields = replacement_query_fields(replacement_query)
    preference = parse_initial_query(replacement_query or "")
    theme = preference.active_theme_labels[0] if preference.active_theme_labels else None
    return {
        **query_fields,
        "theme": theme,
        "mood": "quiet" if raw_query is not None and "조용" in raw_query else None,
        "place_type": "walk" if raw_query is not None and "산책" in raw_query else None,
        "location": None,
        "avoid_content_ids": [
            content_id
            for item in current_order_items
            if _item_int(item, "day") == day
            and (content_id := _optional_text(item.get("contentId", item.get("content_id")))) is not None
        ],
    }


def _is_day_regenerate_query(raw_query: str) -> bool:
    whole_day = any(token in raw_query for token in ("전체", "전부", "통째", "다 ", "싹"))
    action = any(token in raw_query for token in ("바꿔", "변경", "교체", "갈아엎"))
    return whole_day and action


def _target_day(
    raw_query: str,
    current_order_items: tuple[Mapping[str, Any], ...],
) -> int | None:
    numeric_day = _query_int(raw_query, r"(\d+)일차")
    if numeric_day is not None:
        return numeric_day
    if "첫날" in raw_query or "첫 날" in raw_query:
        return 1
    if any(token in raw_query for token in ("둘째 날", "둘째날", "두번째 날", "두 번째 날")):
        return 2
    if "마지막 날" in raw_query or "마지막날" in raw_query:
        return _last_day(current_order_items)
    return None


def _day_replacement_query(raw_query: str) -> str | None:
    normalized = re.sub(
        r"^\s*(\d+일차|첫\s*날|첫날|둘째\s*날|둘째날|두\s*번째\s*날|마지막\s*날|마지막날)\s*",
        "",
        raw_query,
    )
    normalized = re.sub(r"^(전체|전부|통째로?|다|싹)?\s*(일정|코스|장소)?(을|를|은|는)?\s*", "", normalized)
    normalized = re.sub(
        r"(쪽으로|으로|로)?\s*(바꾸고|바꿔줘|바꿔|변경해줘|교체해줘|갈아엎어줘|갈아엎어)\.?$",
        "",
        normalized.strip(" .,。"),
    )
    normalized = re.sub(r"^(전체|전부|통째로?|다|싹)\s*", "", normalized)
    normalized = normalized.strip(" .,。")
    return normalized or None


def _current_order(request: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = request.get("currentOrder", request.get("current_order", ()))
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _last_day(current_order_items: tuple[Mapping[str, Any], ...]) -> int | None:
    days = [_item_int(item, "day") for item in current_order_items]
    values = [day for day in days if day is not None]
    return max(values) if values else None


def _query_int(raw_query: str, pattern: str) -> int | None:
    match = re.search(pattern, raw_query)
    if match is None:
        return None
    return int(match.group(1))


def _item_int(item: Mapping[str, Any], field_name: str) -> int | None:
    value = item.get(field_name)
    if isinstance(value, int):
        return value
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _raw_query(request: Mapping[str, Any]) -> str | None:
    return _optional_text(request.get("rawModifyQuery", request.get("raw_modify_query")))
