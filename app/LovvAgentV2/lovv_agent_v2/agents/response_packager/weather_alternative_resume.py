from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.planner.steps.weather_alternative.exposure import (
    WEATHER_SENSITIVE_EXPOSURES,
    item_exposure,
)
from lovv_agent_v2.tools.runtime_extractors import runtime_tools_from_value
from lovv_agent_v2.agents.response_packager.packager import package_recommendation_response
from lovv_agent_v2.agents.response_packager.weather_route_feasibility import (
    weather_route_feasible,
)
from lovv_agent_v2.agents.response_packager.weather_response_context import (
    weather_planner_output,
    weather_recommendation_id,
    weather_request_payload,
    weather_selected_city,
)
from lovv_agent_v2.agents.response_packager.weather_replacement_selection import (
    replacement_combinations,
    weather_sensitive_targets,
)
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.models.schemas import SchemaValidationError

INDOOR_FALLBACK_QUERY = "실내 관광지 박물관 전시관 실내 체험"
WEATHER_ALTERNATIVE_NOTICE = "날씨 영향을 줄일 수 있도록 실내 중심 대체 일정으로 조정했습니다."
WEATHER_ALTERNATIVE_MIXED_NOTICE = "일부 장소는 실내외 혼합형이라 현장 날씨에 따라 체류 방식을 조정해 주세요."
WEATHER_ALTERNATIVE_FAILURE_NOTICE = "실내 대체 후보가 부족하거나 동선이 맞지 않아 현재 일정으로 유지합니다."
MAX_ROUTE_COMBO_CANDIDATES = 12


def weather_alternative_response_update(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    planner_output = weather_planner_output(state)
    alternative = _alternative_itinerary(state, planner_output)
    output = _planner_with_weather_alternative(planner_output, alternative)
    return {
        "response": {
            "response_status": "modification_pending",
            "response_payload": package_recommendation_response(
                planner_output=output,
                request=weather_request_payload(state),
                selected_city=weather_selected_city(state, output),
                recommendation_id=weather_recommendation_id(response),
                response_status="modification_pending",
            ),
            "clarification_resume": dict(action),
        },
    }


def _alternative_itinerary(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    itinerary = _mapping_sequence(planner_output.get("itinerary"))
    if not itinerary:
        return ()
    targets = weather_sensitive_targets(
        itinerary,
        WEATHER_SENSITIVE_EXPOSURES,
        item_exposure,
    )
    if not targets:
        return tuple(dict(item) for item in itinerary)
    candidates = _replacement_candidates(state, planner_output, targets)
    if len(candidates) < len(targets):
        return ()
    for replacements in replacement_combinations(
        itinerary,
        targets,
        candidates,
        limit=MAX_ROUTE_COMBO_CANDIDATES,
    ):
        alternative = _with_replacements(itinerary, targets, replacements)
        if weather_route_feasible(state, itinerary, alternative):
            return tuple(alternative)
    return ()


def _replacement_candidates(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
    targets: Sequence[int],
) -> tuple[Mapping[str, Any], ...]:
    city_id = _city_id(planner_output)
    excluded_ids = _place_ids(_mapping_sequence(planner_output.get("itinerary")))
    reserve = _indoor_candidates(_reserve_pool(state, planner_output), city_id, excluded_ids)
    if len(reserve) >= len(targets):
        return reserve
    searched = _indoor_search_candidates(state, city_id, excluded_ids | _place_ids(reserve))
    return (*reserve, *searched)


def _with_replacements(
    itinerary: Sequence[Mapping[str, Any]],
    targets: Sequence[int],
    replacements: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    alternative = [dict(item) for item in itinerary]
    for index, replacement in zip(targets, replacements, strict=False):
        alternative[index] = _replacement_item(alternative[index], replacement)
    return tuple(alternative)




def _indoor_search_candidates(
    state: Mapping[str, Any],
    city_id: str | None,
    excluded_ids: set[str],
) -> tuple[Mapping[str, Any], ...]:
    runtime = runtime_value(state, "planner_runtime")
    if runtime is None or city_id is None:
        return ()
    try:
        tools = runtime_tools_from_value(runtime)
    except SchemaValidationError:
        return ()
    if tools is None:
        return ()
    query_vector = tools.embedding.embed_query(INDOOR_FALLBACK_QUERY)
    candidates = tools.destination_search.search_candidates(
        query_vector,
        top_k=50,
        city_id=city_id,
        theme=None,
    )
    return _indoor_candidates(candidates, city_id, excluded_ids)


def _indoor_candidates(
    candidates: Sequence[Any],
    city_id: str | None,
    excluded_ids: set[str],
) -> tuple[Mapping[str, Any], ...]:
    indoor: list[Mapping[str, Any]] = []
    mixed: list[Mapping[str, Any]] = []
    for candidate in candidates:
        payload = _candidate_payload(candidate)
        place_id = _place_id(payload)
        if place_id is None or place_id in excluded_ids:
            continue
        if city_id is not None and _text(payload.get("city_id", payload.get("cityId"))) != city_id:
            continue
        exposure = _indoor_outdoor(payload)
        if exposure == "indoor":
            indoor.append(payload)
        if exposure == "mixed":
            mixed.append(payload)
    return (*indoor, *mixed)


def _planner_with_weather_alternative(
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
            output["user_notice"] = _with_notice(
                output["user_notice"],
                WEATHER_ALTERNATIVE_MIXED_NOTICE,
            )
        audit["alternative_generation_status"] = "generated"
        audit["alternative_includes_mixed"] = _uses_mixed(alternative)
    else:
        output["user_notice"] = _with_notice(output.get("user_notice"), WEATHER_ALTERNATIVE_FAILURE_NOTICE)
        audit["alternative_generation_status"] = "no_candidate"
    validation["weather_audit"] = audit
    output["validation_result"] = validation
    return output


def _uses_mixed(items: Sequence[Mapping[str, Any]]) -> bool:
    return any(_indoor_outdoor(item) == "mixed" for item in items)


def _replacement_item(
    original: Mapping[str, Any],
    replacement: Mapping[str, Any],
) -> dict[str, Any]:
    item = dict(replacement)
    item["day"] = original.get("day", item.get("day", 1))
    item["slot"] = original.get("slot", item.get("slot"))
    if original.get("isSeed") is True or original.get("is_seed") is True:
        item["isSeed"] = True
        item["is_seed"] = True
    item["weather_alternative_replaces"] = _place_id(original)
    item["weather_alternative_source"] = "indoor_candidate"
    if "placeId" not in item and (place_id := _place_id(item)) is not None:
        item["placeId"] = place_id
    if "indoor_outdoor" not in item and (exposure := _indoor_outdoor(item)) is not None:
        item["indoor_outdoor"] = exposure
    item.setdefault("body", "날씨 영향을 줄이기 위해 실내 중심으로 대체한 장소입니다.")
    item.setdefault("reason", "비나 더위 영향을 덜 받는 실내 후보를 우선 반영했습니다.")
    return item


def _reserve_pool(
    state: Mapping[str, Any],
    planner_output: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    planner = _mapping(state.get("planner"))
    context = _mapping(planner.get("modify_context"))
    reserve = _mapping_sequence(context.get("reserve_pool"))
    if reserve:
        return reserve
    validation = _mapping(planner_output.get("validation_result"))
    structure = _mapping(validation.get("itinerary_structure"))
    return _mapping_sequence(structure.get("reserve"))


def _city_id(planner_output: Mapping[str, Any]) -> str | None:
    selected = planner_output.get("selected_city")
    if isinstance(selected, Mapping):
        value = _text(selected.get("city_id", selected.get("cityId")))
        if value is not None:
            return value
    for item in _mapping_sequence(planner_output.get("itinerary")):
        value = _text(item.get("city_id", item.get("cityId")))
        if value is not None:
            return value
    return None


def _candidate_payload(candidate: Any) -> Mapping[str, Any]:
    if isinstance(candidate, Mapping):
        return candidate
    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload if isinstance(payload, Mapping) else {}
    return {}


def _place_ids(items: Sequence[Mapping[str, Any]]) -> set[str]:
    return {place_id for item in items if (place_id := _place_id(item)) is not None}


def _place_id(item: Mapping[str, Any]) -> str | None:
    return _text(item.get("place_id", item.get("placeId", item.get("contentId"))))


def _indoor_outdoor(item: Mapping[str, Any]) -> str | None:
    value = _text(item.get("indoor_outdoor", item.get("indoorOutdoor")))
    if value is None:
        metadata = item.get("metadata")
        if isinstance(metadata, Mapping):
            value = _text(metadata.get("indoor_outdoor", metadata.get("indoorOutdoor")))
    return value.lower() if value is not None else None


def _with_notice(value: Any, notice: str) -> tuple[str, ...]:
    notices = _notice_tuple(value)
    return notices if notice in notices else (*notices, notice)


def _notice_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["weather_alternative_response_update"]
