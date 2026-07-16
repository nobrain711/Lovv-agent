from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.tools.runtime_containers import ItineraryExplanationRuntime
from lovv_agent_v2.tools.travel_time_provider import MatrixResponse, SnapResponse
from lovv_agent_v2.agents.response_packager.clarification_resume import response_resume_update


def test_weather_keep_primary_resume_returns_modification_pending() -> None:
    result = response_resume_update(
        _state(),
        {
            "response_payload": {
                "recommendationId": "REQ-WEATHER",
                "clarification": {
                    "reasonCode": "weather_alternative_available",
                    "options": [
                        {
                            "optionId": "keep_primary_itinerary",
                            "label": "현재 일정 유지",
                            "apply": {},
                            "then": "abort",
                        },
                    ],
                },
            },
        },
        {"selectedOptionId": "keep_primary_itinerary"},
    )

    response = result["response"]
    payload = response["response_payload"]
    assert response["response_status"] == "modification_pending"
    assert "clarification" not in payload
    assert payload["itinerary"]["days"][0]["items"][0]["title"] == "해변 산책"
    assert response["clarification_resume"]["option_id"] == "keep_primary_itinerary"


def test_weather_alternative_resume_rejects_route_infeasible_candidate() -> None:
    result = response_resume_update(
        {
            **_state(),
            "runtime": {"travel_time_provider": FarTravelTimeProvider()},
            "planner": {
                **_state()["planner"],
                "modify_context": {
                    "reserve_pool": [
                        _reserve("attraction#indoor-far", "먼 실내 전시관", 38.5, 130.1),
                        _reserve("attraction#indoor-far-2", "먼 실내 박물관", 38.6, 130.2),
                    ],
                },
            },
        },
        {
            "response_payload": {
                "clarification": {
                    "reasonCode": "weather_alternative_available",
                    "options": [
                        {
                            "optionId": "use_weather_alternative",
                            "label": "날씨 대체 일정 보기",
                            "apply": {},
                            "then": "weather_alternative",
                        },
                    ],
                },
            },
        },
        {"selectedOptionId": "use_weather_alternative"},
    )

    payload = result["response"]["response_payload"]
    items = payload["itinerary"]["days"][0]["items"]
    assert [item["title"] for item in items] == ["해변 산책", "항구 산책"]
    assert "실내 대체 후보가 부족" in payload["explainability"]["userNotice"]


def test_weather_alternative_resume_skips_infeasible_candidate_combination() -> None:
    result = response_resume_update(
        {
            **_state(),
            "runtime": {
                "travel_time_provider": PairTravelTimeProvider(
                    far_pairs={
                        ("attraction#far", "attraction#near-1"),
                        ("attraction#far", "attraction#near-2"),
                    },
                ),
            },
            "planner": {
                **_state()["planner"],
                "modify_context": {
                    "reserve_pool": [
                        _reserve("attraction#far", "먼 실내 전시관", 38.5, 130.1),
                        _reserve("attraction#near-1", "가까운 실내 전시관", 37.5, 129.1),
                        _reserve("attraction#near-2", "가까운 실내 체험관", 37.51, 129.11),
                    ],
                },
            },
        },
        _weather_alternative_response(),
        {"selectedOptionId": "use_weather_alternative"},
    )

    payload = result["response"]["response_payload"]
    items = payload["itinerary"]["days"][0]["items"]
    assert [item["title"] for item in items] == ["가까운 실내 전시관", "가까운 실내 체험관"]
    assert "날씨 영향을 줄일 수 있도록" in payload["explainability"]["userNotice"]


def test_weather_alternative_resume_uses_mixed_after_indoor() -> None:
    result = response_resume_update(
        {
            **_state(),
            "planner": {
                **_state()["planner"],
                "modify_context": {
                    "reserve_pool": [
                        _reserve("attraction#mixed", "실내외 혼합 전망관", 37.52, 129.12, "mixed"),
                        _reserve("attraction#indoor", "실내 전시관", 37.5, 129.1, "indoor"),
                    ],
                },
            },
        },
        _weather_alternative_response(),
        {"selectedOptionId": "use_weather_alternative"},
    )

    payload = result["response"]["response_payload"]
    items = payload["itinerary"]["days"][0]["items"]
    assert [item["title"] for item in items] == ["실내 전시관", "실내외 혼합 전망관"]
    assert [item["indoorOutdoor"] for item in items] == ["indoor", "mixed"]
    assert "실내외 혼합" in payload["explainability"]["userNotice"]


def test_weather_alternative_resume_explains_replaced_items() -> None:
    runtime = PlannerCopyRuntime(
        {
            "structured_output": {
                "item_copies": [
                    {
                        "item_ref": "item:0",
                        "title": "설명된 실내 전시관",
                        "body": "비 오는 날에도 머물기 좋은 실내 전시 공간입니다.",
                        "reason": "야외 해변 대신 날씨 영향을 덜 받는 실내 후보입니다.",
                    },
                ],
                "recommendation_reasons": ["날씨 영향을 줄이기 위해 실내 후보를 반영했습니다."],
                "itinerary_flow_reason": "기존 동선을 유지하며 첫 장소만 실내로 조정했습니다.",
            },
        },
    )

    result = response_resume_update(
        {
            **_state(itinerary=(_item("attraction#outdoor", "해변 산책", 37.5, 129.1),)),
            "runtime": {
                "itinerary_explanation_runtime": ItineraryExplanationRuntime(
                    explanation_runtime=runtime,
                    schema_retry_limit=0,
                ),
            },
            "planner": {
                **_state()["planner"],
                "planner_output": {
                    **_state()["planner"]["planner_output"],
                    "itinerary": (_item("attraction#outdoor", "해변 산책", 37.5, 129.1),),
                },
                "modify_context": {
                    "reserve_pool": [
                        _reserve("attraction#indoor", "실내 전시관", 37.5, 129.1),
                    ],
                },
            },
        },
        _weather_alternative_response(),
        {"selectedOptionId": "use_weather_alternative"},
    )

    item = result["response"]["response_payload"]["itinerary"]["days"][0]["items"][0]
    assert item["title"] == "설명된 실내 전시관"
    assert len(runtime.requests) == 1


class FarTravelTimeProvider:
    def snap_places(self, places, transport_pref):
        return SnapResponse(places=tuple(places), excluded_place_ids=(), audit={})

    def matrix_minutes(self, place_ids, transport_pref):
        durations = {
            (first, second): 0.0 if first == second else 300.0
            for first in place_ids
            for second in place_ids
        }
        return MatrixResponse(durations=durations, audit={"matrix_provider": "fake"})


class PairTravelTimeProvider:
    def __init__(self, far_pairs):
        self._far_pairs = frozenset(frozenset(pair) for pair in far_pairs)

    def snap_places(self, places, transport_pref):
        return SnapResponse(places=tuple(places), excluded_place_ids=(), audit={})

    def matrix_minutes(self, place_ids, transport_pref):
        durations = {}
        for first in place_ids:
            for second in place_ids:
                pair = frozenset((first, second))
                durations[(first, second)] = 300.0 if pair in self._far_pairs else 10.0
        return MatrixResponse(durations=durations, audit={"matrix_provider": "fake"})


def _state(itinerary: tuple[dict, ...] | None = None) -> dict:
    return {
        "request": {
            "request_id": "REQ-WEATHER",
            "country": "KR",
            "travel_month": 7,
            "trip_type": "2d1n",
            "themes": ("바다·해안",),
        },
        "intent": {
            "city_select_input": {
                "country": "KR",
                "travel_month": 7,
                "trip_type": "2d1n",
                "destination_id": "KR-51-170",
                "active_required_themes": ["바다·해안"],
                "include_festivals": False,
            },
        },
        "planner": {
            "planner_output": {
                "itinerary": itinerary
                or (
                    _item("attraction#outdoor", "해변 산책", 37.5, 129.1),
                    _item("attraction#port", "항구 산책", 37.51, 129.11),
                ),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "해안 중심 일정입니다.",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {
                    "planner_status_gate": "ok",
                    "weather_audit": {"status": "alternative_available"},
                },
            },
        },
    }


def _weather_alternative_response() -> dict:
    return {
        "response_payload": {
            "clarification": {
                "reasonCode": "weather_alternative_available",
                "options": [
                    {
                        "optionId": "use_weather_alternative",
                        "label": "날씨 대체 일정 보기",
                        "apply": {},
                        "then": "weather_alternative",
                    },
                ],
            },
        },
    }


def _item(
    place_id: str,
    title: str,
    latitude: float,
    longitude: float,
    exposure: str = "outdoor",
    *,
    is_seed: bool = False,
) -> dict:
    item = {
        "day": 1,
        "slot": "morning",
        "placeId": place_id,
        "title": title,
        "city_id": "KR-51-170",
        "city_name_ko": "동해시",
        "indoor_outdoor": exposure,
        "latitude": latitude,
        "longitude": longitude,
    }
    if is_seed:
        item["isSeed"] = True
    return item


def _reserve(
    place_id: str,
    title: str,
    latitude: float,
    longitude: float,
    exposure: str = "indoor",
) -> dict:
    return {
        "place_id": place_id,
        "title": title,
        "city_id": "KR-51-170",
        "city_name_ko": "동해시",
        "theme_tags": ["예술·감성"],
        "indoor_outdoor": exposure,
        "latitude": latitude,
        "longitude": longitude,
    }


class PlannerCopyRuntime:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[Mapping[str, Any]] = []

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(request)
        return self.response
