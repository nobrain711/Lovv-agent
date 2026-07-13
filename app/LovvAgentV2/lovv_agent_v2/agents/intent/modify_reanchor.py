from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.models.trip_intent import trip_intent_from_mapping


def modify_state_update(
    current_intent: Mapping[str, Any],
    modify_intent: Mapping[str, Any],
    state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    next_intent = {**dict(current_intent), **dict(modify_intent)}
    next_intent["modify_intent"] = dict(modify_intent)
    if _is_city_change(modify_intent):
        next_intent.pop("intent_output", None)
        city_input = _city_change_input(current_intent, modify_intent, state or {})
        _sync_city_change_avoid_ids(next_intent, modify_intent, state or {})
        next_intent["city_select_input"] = city_input
        trip_intent = trip_intent_from_mapping(city_input)
        if trip_intent is not None:
            next_intent["trip_intent"] = trip_intent
        return {
            "intent": next_intent,
            "festival_gate": {},
            "city_select": {},
            "planner": {},
            "response": {},
            "memory": _city_change_memory(modify_intent, state or {}),
        }
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
    state: Mapping[str, Any],
) -> dict[str, Any]:
    city_input = dict(_current_city_input(current_intent))
    city_change = modify_intent["city_change"]
    if not isinstance(city_change, Mapping):
        return city_input
    if modify_intent.get("routing_hint") == "city_select_rediscovery":
        city_input["destination_id"] = None
        city_input["destination_label"] = None
        city_input["city_key"] = None
        city_input["ddb_pk"] = None
        city_input["execution_mode"] = "city_discovery"
        city_input["disliked_city_ids"] = _excluded_city_ids(modify_intent, state)
        _clear_city_preferences(city_input)
        return city_input
    city_input["destination_id"] = city_change.get("target_city_id")
    city_input["destination_label"] = city_change.get("target_city_name")
    city_input["execution_mode"] = "anchored_place_search"
    return city_input


def _current_city_input(current_intent: Mapping[str, Any]) -> Mapping[str, Any]:
    value = current_intent.get("city_select_input")
    return value if isinstance(value, Mapping) else {}


def _excluded_city_ids(
    modify_intent: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[str, ...]:
    city_change = modify_intent.get("city_change")
    values: list[str] = []
    if isinstance(city_change, Mapping):
        _extend_unique(values, city_change.get("avoid_city_ids"))
    memory = state.get("memory")
    if isinstance(memory, Mapping):
        history = memory.get("modify_history")
        if isinstance(history, Mapping):
            _extend_unique(values, history.get("excluded_city_ids"))
    return tuple(values)


def _city_change_memory(
    modify_intent: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    memory = state.get("memory")
    next_memory = dict(memory) if isinstance(memory, Mapping) else {}
    history = next_memory.get("modify_history")
    next_history = dict(history) if isinstance(history, Mapping) else {}
    excluded_city_ids = _excluded_city_ids(modify_intent, state)
    if excluded_city_ids:
        next_history["excluded_city_ids"] = excluded_city_ids
    next_memory["modify_history"] = next_history
    return next_memory


def _sync_city_change_avoid_ids(
    next_intent: dict[str, Any],
    modify_intent: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    normalized = _excluded_city_ids(modify_intent, state)
    if not normalized:
        return
    next_modify_intent = next_intent.get("modify_intent")
    if not isinstance(next_modify_intent, dict):
        return
    city_change = next_modify_intent.get("city_change")
    if not isinstance(city_change, Mapping):
        return
    next_city_change = dict(city_change)
    next_city_change["avoid_city_ids"] = normalized
    next_modify_intent["city_change"] = next_city_change


def _clear_city_preferences(city_input: dict[str, Any]) -> None:
    for key in (
        "preferred_city_ids",
        "preferred_region_ids",
        "preferred_region_spans",
        "preferred_region_names",
    ):
        city_input[key] = ()


def _extend_unique(target: list[str], value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        return
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in target:
            target.append(item.strip())


__all__ = ["modify_state_update"]
