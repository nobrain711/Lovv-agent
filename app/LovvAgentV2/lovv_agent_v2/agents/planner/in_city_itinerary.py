from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)
from lovv_agent_v2.agents.planner.routing import RoutingResult, route_days
from lovv_agent_v2.models.schemas import PlannerOutput, SchemaValidationError

TRIP_PLACE_TARGETS: Mapping[str, int] = {
    "daytrip": 4,
    "2d1n": 8,
    "3d2n": 12,
}


@dataclass(frozen=True, slots=True)
class InCityPlannerInput:
    city_selection_result: Mapping[str, object]
    recommended_places: Sequence[Mapping[str, object]]
    reserve_places: Sequence[Mapping[str, object]]
    active_themes: Sequence[str]
    theme_weights: Mapping[str, float] | None
    trip_type: str
    transport_pref: str
    soft_query: str = ""


def build_in_city_itinerary(planner_input: InCityPlannerInput) -> PlannerOutput:
    selected_city = _mapping(planner_input.city_selection_result.get("selected_city"))
    seeds = _sequence_of_mappings(planner_input.city_selection_result.get("seeds"))
    target_count = TRIP_PLACE_TARGETS.get(planner_input.trip_type, 12)
    selection = build_working_set(
        PlannerSelectionInput(
            raw_places=planner_input.recommended_places,
            soft_places=planner_input.reserve_places,
            seeds=seeds,
            active_themes=planner_input.active_themes,
            theme_weights=planner_input.theme_weights,
            trip_type=planner_input.trip_type,
            target_count=target_count,
        ),
    )
    routed = route_days(
        selection.places,
        trip_type=planner_input.trip_type,
        transport_pref=planner_input.transport_pref,
    )
    itinerary = _itinerary_items(routed)
    status = "ok" if itinerary else "insufficient_candidates"
    notices = _notices(routed, selected_city, status)
    validation = {
        "planner_status_gate": status,
        "selection_audit": selection.audit,
        "route_audit": routed.audit,
    }
    return PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=_recommendation_reasons(planner_input, selected_city),
        itinerary_flow_reason=_flow_reason(routed),
        external_links={},
        confidence=0.76 if status == "ok" else 0.35,
        user_notice=notices,
        validation_result=validation,
        alternative_itinerary=(),
    )


def _itinerary_items(routed: RoutingResult) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    for day in routed.days:
        for order, routed_place in enumerate(day.places, start=1):
            place = routed_place.place
            items.append(
                {
                    "day": day.day,
                    "slot": _slot_for_order(order, len(day.places)),
                    "placeId": place.place_id,
                    "title": place.title,
                    "body": _body(place),
                    "reason": _reason(place),
                    "moveMinutes": routed_place.move_min_from_prev,
                    "latitude": place.latitude,
                    "longitude": place.longitude,
                    "reason_code": _reason_code(place),
                    "evidence": {
                        "similarity": place.similarity,
                        "soft_similarity": place.soft_similarity,
                        "themes": place.theme_tags,
                    },
                },
            )
    return tuple(items)


def _slot_for_order(order: int, count: int) -> str:
    if order == 1:
        return "morning"
    if order == count:
        return "evening"
    return "afternoon"


def _body(place) -> str:
    theme = place.assigned_theme or (place.theme_tags[0] if place.theme_tags else "조건")
    return f"{theme} 조건과 도시 내 동선을 함께 고려한 방문지입니다."


def _reason(place) -> str:
    if place.is_seed:
        return "요청 테마별 seed 장소라 일정에 우선 포함했습니다."
    if place.soft_similarity > place.similarity:
        return "요청 분위기와 테마가 함께 맞아 작업셋에 포함했습니다."
    return "도시 내 관련도와 테마 균형에 맞는 후보입니다."


def _reason_code(place) -> str:
    if place.is_seed:
        return "seed_floor"
    if place.soft_similarity > place.similarity:
        return "soft_theme_gate"
    return "relevance_quota"


def _recommendation_reasons(
    planner_input: InCityPlannerInput,
    selected_city: Mapping[str, object],
) -> tuple[str, ...]:
    city_name = selected_city.get("city_name_ko") or selected_city.get("name") or "선택 도시"
    theme_text = ", ".join(planner_input.active_themes) or "요청 조건"
    reasons = [
        f"{city_name} 안에서 {theme_text} 균형을 우선했습니다.",
        "장소 선택은 관련도 컷, seed 보존, 분위기 보강 순서로 정리했습니다.",
    ]
    if planner_input.soft_query:
        reasons.append("분위기 조건은 같은 테마 안에서 순위를 보정하는 데만 사용했습니다.")
    return tuple(reasons)


def _flow_reason(routed: RoutingResult) -> str:
    day_count = len(routed.days)
    return f"도시 내 후보를 {day_count}개 일자 클러스터로 나누고 이동시간이 낮은 순서로 배치했습니다."


def _notices(
    routed: RoutingResult,
    selected_city: Mapping[str, object],
    status: str,
) -> tuple[str, ...]:
    notices: list[str] = []
    city_name = selected_city.get("city_name_ko") or selected_city.get("name") or "이 도시"
    transport_notice = routed.audit.get("transport_notice")
    if transport_notice == "walking_preference_requires_transit_or_car":
        notices.append(f"walk 선호 기준으로 {city_name}는 대중교통이나 차량 이동을 권장합니다.")
    if transport_notice == "walkable_compact_city":
        notices.append(f"walk 선호 기준으로 {city_name}는 도보 중심으로도 검토할 수 있습니다.")
    if status != "ok":
        notices.append("조건을 만족하는 장소 수가 부족해 대안 도시 재실행이 필요할 수 있습니다.")
    return tuple(notices)


def _sequence_of_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_mapping(item) for item in value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("planner payload must be a mapping")
    return value
