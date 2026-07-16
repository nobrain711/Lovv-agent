from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, TypedDict

from lovv_agent_v2.agents.intent.modify_slots import avoid_city_ids
from lovv_agent_v2.models.city_identity import load_default_city_identity_map
from lovv_agent_v2.models.city_identity_text import find_city_identity_in_text

_GENERIC_CHANGE_PHRASES: Final = (
    "도시 바꿔",
    "도시를 바꿔",
    "도시 변경",
    "도시를 변경",
    "도시 교체",
    "도시를 교체",
    "지역 바꿔",
    "지역을 바꿔",
    "지역 변경",
    "지역을 변경",
    "지역 교체",
    "지역을 교체",
)
_NEGATIVE_CITY_MARKERS: Final = ("말고", "제외", "빼고", "싫")

CurrentOrderValue = str | int | float | bool | None


class CityChange(TypedDict):
    target_city_id: str | None
    target_city_name: str | None
    city_preference_query: str
    carry_over_themes: bool
    carry_over_festivals: bool
    avoid_city_ids: list[str]


def build_city_change(
    raw_query: str,
    current_order: tuple[Mapping[str, CurrentOrderValue], ...],
) -> CityChange | None:
    if "도시" not in raw_query and "지역" not in raw_query:
        return None
    if not any(keyword in raw_query for keyword in ("바꿔", "변경", "교체")):
        return None
    city_map = load_default_city_identity_map()
    identity = find_city_identity_in_text(city_map, raw_query)
    excluded_city_ids = avoid_city_ids(current_order)
    if identity is not None and _city_is_negated(raw_query, identity.city_name_ko):
        if identity.city_id not in excluded_city_ids:
            excluded_city_ids.append(identity.city_id)
        return {
            "target_city_id": None,
            "target_city_name": None,
            "city_preference_query": raw_query,
            "carry_over_themes": True,
            "carry_over_festivals": True,
            "avoid_city_ids": excluded_city_ids,
        }
    if identity is not None:
        return {
            "target_city_id": identity.city_id,
            "target_city_name": identity.city_name_ko,
            "city_preference_query": raw_query,
            "carry_over_themes": True,
            "carry_over_festivals": True,
            "avoid_city_ids": excluded_city_ids,
        }
    if "다른" not in raw_query and not any(
        phrase in raw_query for phrase in _GENERIC_CHANGE_PHRASES
    ):
        return None
    return {
        "target_city_id": None,
        "target_city_name": None,
        "city_preference_query": raw_query,
        "carry_over_themes": True,
        "carry_over_festivals": True,
        "avoid_city_ids": excluded_city_ids,
    }


def _city_is_negated(raw_query: str, city_name: str | None) -> bool:
    if city_name is None:
        return False
    for mention in _city_mentions(city_name):
        pattern = rf"{re.escape(mention)}(?:은|는|이|가|을|를)?\s*(?:{'|'.join(_NEGATIVE_CITY_MARKERS)})"
        if re.search(pattern, raw_query) is not None:
            return True
    return False


def _city_mentions(city_name: str) -> tuple[str, ...]:
    if city_name.endswith(("시", "군", "구")) and len(city_name) > 1:
        return city_name, city_name[:-1]
    return (city_name,)


def city_change_routing_hint(city_change: CityChange) -> str:
    target_id = city_change.get("target_city_id")
    if isinstance(target_id, str) and target_id.strip():
        return "planner_direct_anchor"
    return "city_select_rediscovery"


__all__ = ["build_city_change", "city_change_routing_hint"]
