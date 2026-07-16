from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def has_pending_explanation_scope(validation: Mapping[str, Any]) -> bool:
    if (
        validation.get("modification_explanation_completed") is True
        or validation.get("modification_explanation_attempted") is True
    ):
        return False
    value = validation.get("explanation_item_place_ids")
    if isinstance(value, (list, tuple)) and bool(value):
        return True
    return validation.get("modification_status") == "applied" and isinstance(
        validation.get("applied_edit"),
        Mapping,
    )


def has_post_explain_weather(state: Mapping[str, Any]) -> bool:
    weather_audit = _planner_validation(state).get("weather_audit")
    return isinstance(weather_audit, Mapping) and weather_audit.get("evaluation_stage") == "post_explain"


def _planner_validation(state: Mapping[str, Any]) -> Mapping[str, Any]:
    planner = state.get("planner")
    if not isinstance(planner, Mapping):
        return {}
    validation = planner.get("validation_result")
    if isinstance(validation, Mapping):
        return validation
    planner_output = planner.get("planner_output")
    if isinstance(planner_output, Mapping):
        output_validation = planner_output.get("validation_result")
        if isinstance(output_validation, Mapping):
            return output_validation
    return {}
