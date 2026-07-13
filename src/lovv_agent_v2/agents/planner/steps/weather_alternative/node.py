from __future__ import annotations

from collections.abc import Mapping, Sequence

from lovv_agent_v2.agents.planner.steps.weather_alternative.exposure import summarize_exposure
from lovv_agent_v2.agents.planner.steps.weather_alternative.policy import (
    WeatherDecisionPolicy,
    decide_weather,
)
from lovv_agent_v2.agents.planner.steps.weather_alternative.resource import (
    WeatherRiskIndex,
    load_default_weather_risk_index,
)
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.core.state import UnifiedAgentState


def weather_alternative_node(state: UnifiedAgentState) -> dict[str, object]:
    planner = _mapping(state.get("planner"))
    planner_output = _mapping(planner.get("planner_output"))
    itinerary = _mapping_sequence(planner_output.get("itinerary"))
    if not itinerary:
        return {"planner": _planner_with_unavailable_weather(planner, planner_output, "empty_itinerary")}
    summary = summarize_exposure(itinerary)
    city_id = _city_id(planner_output, itinerary)
    travel_month = _travel_month(state)
    risk = _weather_index(state).lookup(city_id, travel_month)
    decision = decide_weather(
        risk,
        known_count=summary.known_count,
        sensitive_count=summary.sensitive_count,
        policy=WeatherDecisionPolicy(),
    )
    validation = dict(_mapping(planner_output.get("validation_result")))
    validation["weather_audit"] = {
        **decision.audit(risk, summary.known_count, summary.sensitive_count),
        "exposure_counts": dict(summary.counts),
        "evaluation_stage": _evaluation_stage(planner_output),
        "unavailable_reason": _unavailable_reason(city_id, travel_month, risk),
    }
    output = dict(planner_output)
    output["validation_result"] = validation
    if decision.notice is not None:
        output["user_notice"] = _with_notice(output.get("user_notice"), decision.notice)
    planner["planner_output"] = output
    planner["validation_result"] = validation
    planner["weather_risk"] = validation["weather_audit"]
    return {"planner": planner}


def _planner_with_unavailable_weather(
    planner: dict[str, object],
    planner_output: Mapping[str, object],
    reason: str,
) -> dict[str, object]:
    validation = dict(_mapping(planner_output.get("validation_result")))
    validation["weather_audit"] = {
        "status": "unavailable",
        "evaluation_stage": _evaluation_stage(planner_output),
        "unavailable_reason": reason,
    }
    output = dict(planner_output)
    output["validation_result"] = validation
    planner["planner_output"] = output
    planner["validation_result"] = validation
    planner["weather_risk"] = validation["weather_audit"]
    return planner


def _weather_index(state: UnifiedAgentState) -> WeatherRiskIndex:
    value = runtime_value(state, "weather_risk_index")
    if isinstance(value, WeatherRiskIndex):
        return value
    return load_default_weather_risk_index()


def _evaluation_stage(planner_output: Mapping[str, object]) -> str:
    validation = _mapping(planner_output.get("validation_result"))
    if (
        "planner_copy_generation_used_llm" in validation
        or "detail_enrichment_warning_count" in validation
        or "itinerary_explanation_item_count" in validation
    ):
        return "post_explain"
    return "planner"


def _unavailable_reason(
    city_id: str | None,
    travel_month: int | None,
    risk: object | None,
) -> str | None:
    if city_id is None:
        return "missing_city_id"
    if travel_month is None:
        return "missing_travel_month"
    if risk is None:
        return "city_weather_map_missing"
    return None


def _city_id(planner_output: Mapping[str, object], itinerary: Sequence[Mapping[str, object]]) -> str | None:
    selected_city = _mapping(planner_output.get("selected_city"))
    if selected_city:
        value = selected_city.get("city_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    for item in itinerary:
        value = item.get("city_id") or item.get("cityId")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _travel_month(state: UnifiedAgentState) -> int | None:
    intent = _mapping(state.get("intent"))
    city_input = _mapping(intent.get("city_select_input"))
    value = city_input.get("travel_month") or city_input.get("travelMonth")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(normalized for item in value if (normalized := _mapping(item)))


def _notice_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _with_notice(value: object, notice: str) -> tuple[str, ...]:
    notices = _notice_tuple(value)
    return notices if notice in notices else (*notices, notice)


__all__ = ["weather_alternative_node"]
