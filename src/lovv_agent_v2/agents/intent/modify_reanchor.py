from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.models.trip_intent import trip_intent_from_mapping


def modify_state_update(
    current_intent: Mapping[str, Any],
    modify_intent: Mapping[str, Any],
) -> dict[str, Any]:
    next_intent = {**dict(current_intent), **dict(modify_intent)}
    next_intent["modify_intent"] = dict(modify_intent)
    if _is_city_change(modify_intent):
        next_intent.pop("intent_output", None)
        city_input = _city_change_input(current_intent, modify_intent)
        next_intent["city_select_input"] = city_input
        trip_intent = trip_intent_from_mapping(city_input)
        if trip_intent is not None:
            next_intent["trip_intent"] = trip_intent
        return {"intent": next_intent, "city_select": {}, "planner": {}, "response": {}}
    return {"intent": next_intent}


def _is_city_change(modify_intent: Mapping[str, Any]) -> bool:
    return (
        modify_intent.get("status") == "ok"
        and modify_intent.get("kind") == "city_change"
        and isinstance(modify_intent.get("city_change"), Mapping)
    )


def _city_change_input(
    current_intent: Mapping[str, Any],
    modify_intent: Mapping[str, Any],
) -> dict[str, Any]:
    city_input = dict(_current_city_input(current_intent))
    city_change = modify_intent["city_change"]
    if isinstance(city_change, Mapping):
        city_input["destination_id"] = city_change.get("target_city_id")
        city_input["destination_label"] = city_change.get("target_city_name")
    city_input["execution_mode"] = "anchored_place_search"
    return city_input


def _current_city_input(current_intent: Mapping[str, Any]) -> Mapping[str, Any]:
    value = current_intent.get("city_select_input", current_intent.get("intent_output"))
    return value if isinstance(value, Mapping) else {}


__all__ = ["modify_state_update"]
