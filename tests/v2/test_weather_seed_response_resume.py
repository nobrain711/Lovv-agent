from __future__ import annotations

from lovv_agent_v2.tools.travel_time_provider import MatrixResponse, SnapResponse
from lovv_agent_v2.agents.response_packager.clarification_resume import response_resume_update


def test_weather_alternative_resume_keeps_indoor_seed() -> None:
    state = _state(
        (
            _item("attraction#seed", "실내 대표관", 37.5, 129.1, "indoor", is_seed=True),
            _item("attraction#outdoor", "야외 산책", 37.51, 129.11),
        ),
    )

    result = response_resume_update(
        {
            **state,
            "runtime": {"travel_time_provider": PermissiveTravelTimeProvider()},
            "planner": {
                **state["planner"],
                "modify_context": {
                    "reserve_pool": (_reserve("attraction#indoor-1", "실내 전시관", 37.52, 129.12),),
                },
            },
        },
        _weather_alternative_response(),
        {"selectedOptionId": "use_weather_alternative"},
    )

    items = result["response"]["response_payload"]["itinerary"]["days"][0]["items"]
    assert [item["title"] for item in items] == ["실내 대표관", "실내 전시관"]
    assert items[0]["isSeed"] is True


def test_weather_alternative_resume_replaces_outdoor_seed_with_medoid_candidate() -> None:
    state = _state(
        (
            _item("attraction#seed", "야외 대표점", 0.0, 0.0, is_seed=True),
            _item("attraction#outdoor", "야외 산책", 10.0, 10.0),
        ),
    )

    result = response_resume_update(
        {
            **state,
            "runtime": {"travel_time_provider": PermissiveTravelTimeProvider()},
            "planner": {
                **state["planner"],
                "modify_context": {
                    "reserve_pool": (
                        _reserve("attraction#edge", "가장자리 실내관", 0.0, 0.0),
                        _reserve("attraction#center", "중심 실내관", 5.0, 5.0),
                        _reserve("attraction#other", "다른 실내관", 10.0, 10.0),
                    ),
                },
            },
        },
        _weather_alternative_response(),
        {"selectedOptionId": "use_weather_alternative"},
    )

    items = result["response"]["response_payload"]["itinerary"]["days"][0]["items"]
    assert items[0]["title"] == "중심 실내관"
    assert items[0]["isSeed"] is True
    assert items[1]["title"] in {"가장자리 실내관", "다른 실내관"}


class PermissiveTravelTimeProvider:
    def snap_places(self, places, transport_pref):
        return SnapResponse(places=tuple(places), excluded_place_ids=(), audit={})

    def matrix_minutes(self, place_ids, transport_pref):
        return MatrixResponse(
            durations={(first, second): 0.0 for first in place_ids for second in place_ids},
            audit={"matrix_provider": "fake"},
        )


def _state(itinerary: tuple[dict, ...]) -> dict:
    return {
        "request": {"request_id": "REQ-WEATHER", "country": "KR", "travel_month": 7, "trip_type": "2d1n"},
        "intent": {"city_select_input": {"country": "KR", "travel_month": 7, "trip_type": "2d1n"}},
        "planner": {
            "planner_output": {
                "itinerary": itinerary,
                "recommendation_reasons": (),
                "itinerary_flow_reason": "해안 중심 일정입니다.",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {"planner_status_gate": "ok", "weather_audit": {"status": "alternative_available"}},
            },
        },
    }


def _weather_alternative_response() -> dict:
    return {
        "response_payload": {
            "clarification": {
                "reasonCode": "weather_alternative_available",
                "options": [{"optionId": "use_weather_alternative", "apply": {}, "then": "weather_alternative"}],
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
    item = _reserve(place_id, title, latitude, longitude, exposure)
    item["placeId"] = item.pop("place_id")
    item["day"] = 1
    item["slot"] = "morning"
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
        "indoor_outdoor": exposure,
        "latitude": latitude,
        "longitude": longitude,
    }
