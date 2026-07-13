from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.planner.state.context import planner_city_input


def residual_discovery_query(state: Mapping[str, Any]) -> str:
    city_name = _city_name(state)
    return f"{city_name} 여행지" if city_name is not None else "여행지"


def _city_name(state: Mapping[str, Any]) -> str | None:
    city_input = planner_city_input(state)
    for key in ("destination_label", "city_name_ko", "cityName"):
        text = _optional_text(city_input.get(key))
        if text is not None:
            return text
    request = _request(state)
    for item in current_order(request, state):
        for key in ("cityName", "city_name_ko"):
            text = _optional_text(item.get(key))
            if text is not None:
                return text
    for item in _planner_items(state):
        text = _optional_text(item.get("city_name_ko", item.get("cityName")))
        if text is not None:
            return text
    return None


def _planner_items(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    planner = _mapping(state.get("planner"))
    output = _mapping(planner.get("planner_output"))
    value = output.get("itinerary")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _request(state: Mapping[str, Any]) -> Mapping[str, Any]:
    request = state.get("request")
    return request if isinstance(request, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
