from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.response_packager.explain_itinerary import (
    ItineraryExplanationInput,
    explain_planner_output,
)
from lovv_agent_v2.agents.response_packager.weather_response_context import (
    weather_selected_city,
)
from lovv_agent_v2.models.schemas import PlannerOutput
from lovv_agent_v2.tools.runtime_extractors import itinerary_explanation_runtime_from_state

WEATHER_ALTERNATIVE_NOTICE = "날씨 영향을 줄일 수 있도록 실내 중심 대체 일정으로 조정했습니다."
WEATHER_ALTERNATIVE_MIXED_NOTICE = "일부 장소는 실내외 혼합형이라 현장 날씨에 따라 체류 방식을 조정해 주세요."
WEATHER_ALTERNATIVE_FAILURE_NOTICE = "실내 대체 후보가 부족하거나 동선이 맞지 않아 현재 일정으로 유지합니다."


def explained_weather_output(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
) -> Mapping[str, Any]:
    runtime = itinerary_explanation_runtime_from_state(state)
    if runtime.explanation_runtime is None:
        return planner_output
    return explain_planner_output(
        ItineraryExplanationInput(
            planner_output=PlannerOutput.from_mapping(planner_output),
            selected_city=weather_selected_city(state, planner_output) or {},
            query=_query_payload(state),
            runtime=runtime,
        ),
    ).to_dict()


def weather_alternative_place_ids(items: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        place_id
        for item in items
        if item.get("weather_alternative_replaces") is not None
        if (place_id := _place_id(item)) is not None
    )


def planner_with_weather_alternative(
    planner_output: Mapping[str, Any],
    alternative: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output = dict(planner_output)
    validation = dict(_mapping(planner_output.get("validation_result")))
    audit = dict(_mapping(validation.get("weather_audit")))
    if alternative:
        output["itinerary"] = tuple(dict(item) for item in alternative)
        output["user_notice"] = _with_notice(output.get("user_notice"), WEATHER_ALTERNATIVE_NOTICE)
        if _uses_mixed(alternative):
            output["user_notice"] = _with_notice(output["user_notice"], WEATHER_ALTERNATIVE_MIXED_NOTICE)
        audit["alternative_generation_status"] = "generated"
        audit["alternative_includes_mixed"] = _uses_mixed(alternative)
        validation["explanation_item_place_ids"] = weather_alternative_place_ids(alternative)
        for marker in (
            "planner_copy_generation_used_llm",
            "detail_enrichment_warning_count",
            "detail_enrichment_warnings",
            "itinerary_explanation_item_count",
            "modification_explanation_attempted",
            "modification_explanation_completed",
        ):
            validation.pop(marker, None)
    else:
        output["user_notice"] = _with_notice(output.get("user_notice"), WEATHER_ALTERNATIVE_FAILURE_NOTICE)
        audit["alternative_generation_status"] = "no_candidate"
    validation["weather_audit"] = audit
    output["validation_result"] = validation
    return output


def _query_payload(state: Mapping[str, Any]) -> Mapping[str, Any]:
    city_input = _mapping(_mapping(state.get("intent")).get("city_select_input"))
    return {
        "cleaned_raw_query": city_input.get("cleaned_raw_query"),
        "soft_preference_query": city_input.get("soft_preference_query"),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _place_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("placeId", item.get("place_id"))
    return value.strip() if isinstance(value, str) and value.strip() else None


def _uses_mixed(items: Sequence[Mapping[str, Any]]) -> bool:
    return any(_indoor_outdoor(item) == "mixed" for item in items)


def _indoor_outdoor(item: Mapping[str, Any]) -> str | None:
    value = item.get("indoor_outdoor", item.get("indoorOutdoor"))
    return value.strip() if isinstance(value, str) and value.strip() else None


def _notice_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _with_notice(value: Any, notice: str) -> tuple[str, ...]:
    notices = _notice_tuple(value)
    return notices if notice in notices else (*notices, notice)
