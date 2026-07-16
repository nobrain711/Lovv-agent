from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.modify_parser import (
    build_modify_intent,
    missing_current_itinerary_result,
)
from lovv_agent_v2.agents.intent.modify_prompt import prompt_modify_intent_from_request
from lovv_agent_v2.models.trip_intent import trip_intent_from_intent
from lovv_agent_v2.tools.runtime_extractors import intent_prompt_runtime_from_state


def resolve_modify_intent(
    state: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    parsed_rule_result = build_modify_intent(request, state)
    rule_result = _with_current_itinerary_invariant(
        state,
        parsed_rule_result,
        parsed_rule_result,
    )
    if _is_rule_terminal_planner_intent(rule_result):
        return rule_result
    prompt_runtime = intent_prompt_runtime_from_state(state)
    if prompt_runtime.runtime is None:
        return rule_result
    prompt_result = prompt_modify_intent_from_request(
        runtime=prompt_runtime.runtime,
        request=request,
        retry_limit=prompt_runtime.schema_retry_limit,
    )
    if prompt_result is None:
        return rule_result
    if _should_keep_rule_modify_intent(rule_result, prompt_result):
        return rule_result
    return _with_current_itinerary_invariant(state, prompt_result, parsed_rule_result)


def _with_current_itinerary_invariant(
    state: Mapping[str, Any],
    modify_intent: dict[str, Any],
    missing_base: Mapping[str, Any],
) -> dict[str, Any]:
    if modify_intent.get("status") != "ok" or modify_intent.get("kind") != "city_change":
        return modify_intent
    intent = state.get("intent")
    if isinstance(intent, Mapping) and trip_intent_from_intent(intent) is not None:
        return modify_intent
    return missing_current_itinerary_result(missing_base)


def _is_rule_terminal_planner_intent(modify_intent: Mapping[str, Any]) -> bool:
    return modify_intent.get("status") == "ok" and modify_intent.get("kind") in {"city_change", "day_regenerate"}


def _should_keep_rule_modify_intent(
    rule_result: Mapping[str, Any],
    prompt_result: Mapping[str, Any],
) -> bool:
    if rule_result.get("status") != "ok" or rule_result.get("kind") != "slot_replace":
        return False
    edit_ops = rule_result.get("edit_ops")
    if isinstance(edit_ops, Sequence) and not isinstance(edit_ops, (str, bytes)) and len(edit_ops) > 1:
        return True
    if prompt_result.get("status") != "needs_clarification":
        return False
    clarification = prompt_result.get("clarification")
    return (
        isinstance(clarification, Mapping)
        and clarification.get("reason_code") == "modify_target_unresolved"
    )


__all__ = ["resolve_modify_intent"]
