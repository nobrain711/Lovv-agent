from __future__ import annotations

from collections.abc import Mapping

from lovv_agent_v2.agents.planner.state.context import (
    city_selection_result,
    float_value,
    int_value,
    mapping,
    mapping_sequence,
    optional_mapping,
    optional_text,
    place_id,
    planner_input,
    selected_city,
    string_tuple,
    text,
)
from lovv_agent_v2.agents.planner.state.scratch import planner_scratch_mapping, planner_state_update
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import slot_label_for_order
from lovv_agent_v2.models.schemas import PlannerOutput


def assemble_itinerary_node(state: Mapping[str, object]) -> dict[str, object]:
    current_input = planner_input(state)
    route_payload = planner_scratch_mapping(state, "route", "planner.scratch.route")
    selection_payload = planner_scratch_mapping(state, "selection", "planner.scratch.selection")
    city_payload = selected_city(state)
    itinerary = _itinerary_items(route_payload)
    selection_audit = mapping(selection_payload.get("audit"), "planner.scratch.selection.audit")
    minimum_required = int_value(
        selection_audit.get("min_count", current_input["min_count"]),
        "min_count",
    )
    status = "ok" if len(itinerary) >= minimum_required else "insufficient_candidates"
    validation = _validation_result(
        state=state,
        status=status,
        route_payload=route_payload,
        selection_payload=selection_payload,
        itinerary=itinerary,
    )
    output = PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=_recommendation_reasons(current_input, city_payload),
        itinerary_flow_reason=_flow_reason(route_payload),
        external_links={},
        confidence=0.76 if status == "ok" else 0.35,
        user_notice=_notices(route_payload, city_payload, status, validation),
        validation_result=validation,
        alternative_itinerary=(),
    )
    return planner_state_update(
        state,
        public_updates={
            "planner_output": output.to_dict(),
            "validation_result": output.validation_result,
            "modify_context": _modify_context(state, route_payload),
            "modification": None,
            "alternative_itinerary": list(output.alternative_itinerary),
            "fallback": _planner_fallback(state),
            "audit": output.validation_result.get("planner_audit", {}),
        },
    )


def _validation_result(
    *,
    state: Mapping[str, object],
    status: str,
    route_payload: Mapping[str, object],
    selection_payload: Mapping[str, object],
    itinerary: tuple[dict[str, object], ...],
) -> dict[str, object]:
    city_selection = city_selection_result(state)
    alternative = optional_mapping(city_selection.get("alternative_city"))
    alternative_city = alternative.get("city_id") if alternative and status != "ok" else None
    return {
        "planner_status_gate": status,
        "alternative_city_recommended": alternative_city,
        "selection_audit": mapping(selection_payload.get("audit"), "planner.scratch.selection.audit"),
        "route_audit": mapping(route_payload.get("audit"), "planner.scratch.route.audit"),
        "planner_audit": {
            "subgraph_nodes": ("retrieve_places", "route_days", "assemble_itinerary"),
            "thin_city_fallback_policy": "alternative_city_notice",
            "itinerary_count": len(itinerary),
        },
        "itinerary_structure": {
            "days": route_payload.get("days", ()),
            "reserve": route_payload.get("reserve", ()),
        },
    }


def _itinerary_items(route_payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    days = mapping_sequence(route_payload.get("days"))
    day_count = len(days)
    for day in days:
        day_number = int_value(day.get("day"), "day")
        places = mapping_sequence(day.get("places"))
        for order, routed_place in enumerate(places, start=1):
            place = mapping(routed_place.get("place"), "routed_place.place")
            items.append(_itinerary_item(day_number, day_count, order, len(places), routed_place, place))
    return tuple(items)


def _itinerary_item(
    day_number: int,
    day_count: int,
    order: int,
    count: int,
    routed_place: Mapping[str, object],
    place: Mapping[str, object],
) -> dict[str, object]:
    item_type = text(place.get("item_type", "attraction"), "item_type")
    item = {
        "day": day_number,
        "slot": slot_label_for_order(day_number, day_count, order, count),
        "item_type": item_type,
        "placeId": place_id(place),
        "title": text(place.get("title"), "title"),
        "body": _body(place),
        "reason": _reason(place),
        "moveMinutes": int_value(routed_place.get("move_min_from_prev"), "move_min_from_prev"),
        "latitude": place.get("latitude"),
        "longitude": place.get("longitude"),
        "city_id": place.get("city_id"),
        "city_name_ko": place.get("city_name_ko"),
        "indoor_outdoor": _indoor_outdoor(place),
        "theme_tags": tuple(string_tuple(place.get("theme_tags", ()))),
        "source": place.get("source"),
        "ddb_pk": place.get("ddb_pk"),
        "ddb_sk": place.get("ddb_sk"),
        "isSeed": place.get("is_seed") is True,
        "reason_code": _reason_code(place),
        "evidence": {
            "similarity": place.get("similarity", place.get("raw_similarity", 0.0)),
            "soft_similarity": place.get("soft_similarity", 0.0),
            "themes": place.get("theme_tags", ()),
        },
    }
    if item_type == "festival":
        item["festivalId"] = text(place.get("festivalId", place.get("festival_id")), "festival_id")
        _add_optional(item, "eventStartDate", place.get("event_start_date", place.get("start_date")))
        _add_optional(item, "eventEndDate", place.get("event_end_date", place.get("end_date")))
        _add_optional(item, "dateStatus", place.get("date_status"))
    return item


def _indoor_outdoor(place: Mapping[str, object]) -> str:
    value = optional_text(place.get("indoor_outdoor")) or optional_text(place.get("indoorOutdoor"))
    if value in {"indoor", "outdoor", "mixed", "unknown"}:
        return value
    return "unknown"


def _body(place: Mapping[str, object]) -> str:
    if place.get("item_type") == "festival":
        start = optional_text(place.get("event_start_date", place.get("start_date")))
        end = optional_text(place.get("event_end_date", place.get("end_date")))
        if start and end:
            return f"{start}부터 {end}까지 열리는 축제 일정입니다."
        if start:
            return f"{start}에 열리는 축제 일정입니다."
        return "요청한 축제 포함 조건에 맞춰 확인된 축제 일정입니다."
    tags = string_tuple(place.get("theme_tags", ()))
    theme = optional_text(place.get("assigned_theme")) or (tags[0] if tags else "조건")
    return f"{theme} 조건과 도시 내 동선을 함께 고려한 방문지입니다."


def _reason(place: Mapping[str, object]) -> str:
    if place.get("item_type") == "festival" and place.get("is_seed") is True:
        return "요청한 축제 포함 조건에 맞아 일정에 우선 배치했습니다."
    if place.get("is_seed") is True:
        return "요청 테마를 대표하는 장소라 일정에 우선 포함했습니다."
    if float_value(place.get("soft_similarity")) > float_value(place.get("similarity", place.get("raw_similarity"))):
        return "요청 분위기와 테마가 함께 맞아 작업셋에 포함했습니다."
    return "도시 내 관련도와 테마 균형에 맞는 후보입니다."


def _reason_code(place: Mapping[str, object]) -> str:
    if place.get("is_seed") is True:
        return "seed_floor"
    if float_value(place.get("soft_similarity")) > float_value(place.get("similarity", place.get("raw_similarity"))):
        return "soft_theme_gate"
    return "relevance_quota"


def _add_optional(item: dict[str, object], key: str, value: object) -> None:
    normalized = optional_text(value)
    if normalized is not None:
        item[key] = normalized


def _recommendation_reasons(
    current_input: Mapping[str, object],
    city_payload: Mapping[str, object],
) -> tuple[str, ...]:
    city_name = city_payload.get("city_name_ko") or city_payload.get("name") or "선택 도시"
    theme_text = ", ".join(string_tuple(current_input.get("active_themes", ()))) or "요청 조건"
    reasons = [
        f"{city_name} 안에서 {theme_text} 균형을 우선했습니다.",
        "장소 선택은 테마 적합성, 대표 장소 유지, 분위기 보강 순서로 정리했습니다.",
    ]
    if optional_text(current_input.get("soft_query")):
        reasons.append("분위기 조건은 같은 도시와 테마 안에서 순위를 보정하는 데만 사용했습니다.")
    return tuple(reasons)


def _flow_reason(route_payload: Mapping[str, object]) -> str:
    days = mapping_sequence(route_payload.get("days"))
    return f"도시 내 후보를 {len(days)}개 일자로 나누고 이동시간이 낮은 순서로 배치했습니다."


def _notices(
    route_payload: Mapping[str, object],
    city_payload: Mapping[str, object],
    status: str,
    validation: Mapping[str, object],
) -> tuple[str, ...]:
    notices: list[str] = []
    city_name = city_payload.get("city_name_ko") or city_payload.get("name") or "이 도시"
    route_audit = mapping(route_payload.get("audit"), "planner.scratch.route.audit")
    transport_notice = route_audit.get("transport_notice")
    if transport_notice == "walking_preference_requires_transit_or_car":
        notices.append(f"walk 선호 기준으로 {city_name}는 대중교통이나 차량 이동을 권장합니다.")
    if transport_notice == "walkable_compact_city":
        notices.append(f"walk 선호 기준으로 {city_name}는 도보 중심으로도 검토할 수 있습니다.")
    if status != "ok":
        notices.append("조건을 만족하는 장소 수가 부족해 대안 도시 재실행이 필요할 수 있습니다.")
    if validation.get("alternative_city_recommended"):
        notices.append("대안 도시 후보를 함께 남겨 후속 재실행에 사용할 수 있습니다.")
    return tuple(notices)


def _planner_fallback(state: Mapping[str, object]) -> Mapping[str, object] | None:
    planner = optional_mapping(state.get("planner"))
    if planner is None:
        return None
    fallback = optional_mapping(planner.get("fallback"))
    return dict(fallback) if fallback is not None else None


def _modify_context(
    state: Mapping[str, object],
    route_payload: Mapping[str, object],
) -> dict[str, object]:
    planner = optional_mapping(state.get("planner"))
    context = optional_mapping(planner.get("modify_context")) if planner is not None else None
    current = dict(context) if context is not None else {}
    current.setdefault("reserve_pool", route_payload.get("reserve", ()))
    return current
