from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_regenerates_one_day_from_reserve_pool() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _day_regenerate_intent(),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "새 첫 장소", 35.829, 129.214),
                        _candidate("attraction#new-2", "새 둘째 장소", 35.831, 129.216),
                        _candidate("attraction#new-3", "새 셋째 장소", 35.833, 129.218),
                    ],
                },
            },
        },
    )

    planner = result["planner"]
    itinerary = planner["planner_output"]["itinerary"]
    assert [item["title"] for item in itinerary] == ["새 둘째 장소", "새 첫 장소", "새 셋째 장소"]
    assert [item["order"] for item in itinerary] == [1, 2, 3]
    assert planner["modify_context"]["applied_edit"]["reason_code"] == "modify_day_regenerate"


def test_apply_edit_day_regenerate_with_query_excludes_existing_itinerary_items() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _day_regenerate_intent(replacement_query="바다 산책"),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    [
                        _candidate("attraction#seed", "기존 시드", 35.8296, 129.2147),
                        _candidate("attraction#old", "기존 둘째", 35.8326, 129.219),
                        _candidate("attraction#third", "기존 셋째", 35.817, 129.2144),
                        _candidate("attraction#new-1", "새 첫 장소", 35.829, 129.214),
                        _candidate("attraction#new-2", "새 둘째 장소", 35.831, 129.216),
                        _candidate("attraction#new-3", "새 셋째 장소", 35.833, 129.218),
                    ],
                ),
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert {item["placeId"] for item in itinerary} == {
        "attraction#new-1",
        "attraction#new-2",
        "attraction#new-3",
    }


def test_apply_edit_day_regenerate_backfills_when_reserve_is_insufficient() -> None:
    runtime = _FakePlannerRuntime(
        [
            _candidate("attraction#seed", "기존 시드", 35.8296, 129.2147),
            _candidate("attraction#new-1", "새 첫 장소", 35.831, 129.216),
            _candidate("attraction#new-2", "새 둘째 장소", 35.833, 129.218),
        ],
    )
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _day_regenerate_intent(),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#reserve", "예비 장소", 35.829, 129.214),
                    ],
                },
            },
            "runtime": {"planner_runtime": runtime},
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert {item["placeId"] for item in itinerary} == {
        "attraction#reserve",
        "attraction#new-1",
        "attraction#new-2",
    }
    assert runtime.embedding.queries == ["경주시 여행지"]


def test_apply_edit_day_regenerate_uses_current_order_without_checkpoint_output() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _day_regenerate_intent(),
            "planner": {
                "planner_output": {"itinerary": (), "validation_result": {"planner_status_gate": "ok"}},
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "새 첫 장소", 35.829, 129.214),
                        _candidate("attraction#new-2", "새 둘째 장소", 35.831, 129.216),
                        _candidate("attraction#new-3", "새 셋째 장소", 35.833, 129.218),
                    ],
                },
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert len(itinerary) == 3
    assert {item["placeId"] for item in itinerary} == {
        "attraction#new-1",
        "attraction#new-2",
        "attraction#new-3",
    }


def _day_regenerate_intent(replacement_query: str | None = None) -> dict[str, object]:
    return {
        "intent_type": "modification",
        "city_select_input": {
            "country": "KR",
            "travel_month": 10,
            "trip_type": "2d1n",
            "active_required_themes": ("역사·전통",),
            "cleaned_raw_query": "경주 역사 산책",
            "destination_id": "KR-47-130",
            "include_festivals": False,
        },
        "modify_intent": {
            "status": "ok",
            "kind": "day_regenerate",
            "routing_hint": "planner_apply_edit",
            "day_regenerate": {
                "day": 1,
                "condition": {"replacement_query": replacement_query, "theme": None, "avoid_content_ids": []},
            },
        },
    }


def _request_current_order() -> dict[str, object]:
    return {
        "request_id": "REQ-EDIT",
        "country": "KR",
        "travel_month": 10,
        "trip_type": "2d1n",
        "destinationId": "KR-47-130",
        "currentOrder": [
            _order_item("item-1", "attraction#seed", "경주 교촌마을", 1, 1, 35.8296, 129.2147, True),
            _order_item("item-2", "attraction#old", "경주 계림", 1, 2, 35.8326, 129.219, False),
            _order_item("item-3", "attraction#third", "육부전", 1, 3, 35.817, 129.2144, False),
        ],
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": [
            _planner_item("attraction#seed", "경주 교촌마을", 1, 1, 35.8296, 129.2147, True),
            _planner_item("attraction#old", "경주 계림", 1, 2, 35.8326, 129.219, False),
            _planner_item("attraction#third", "육부전", 1, 3, 35.817, 129.2144, False),
        ],
        "recommendation_reasons": ("경주시 안에서 역사·전통 균형을 우선했습니다.",),
        "itinerary_flow_reason": "기존 일정입니다.",
        "external_links": {},
        "confidence": 0.76,
        "user_notice": (),
        "validation_result": {"planner_status_gate": "ok"},
        "alternative_itinerary": (),
    }


def _order_item(
    item_id: str,
    content_id: str,
    title: str,
    day: int,
    order: int,
    latitude: float,
    longitude: float,
    is_seed: bool,
) -> dict[str, object]:
    return {
        "itemId": item_id,
        "contentId": content_id,
        "itemType": "attraction",
        "day": day,
        "order": order,
        "title": title,
        "isSeed": is_seed,
        "cityId": "KR-47-130",
        "theme": "역사·전통",
        "latitude": latitude,
        "longitude": longitude,
    }


def _planner_item(
    place_id: str,
    title: str,
    day: int,
    order: int,
    latitude: float,
    longitude: float,
    is_seed: bool,
) -> dict[str, object]:
    return {
        "day": day,
        "order": order,
        "slot": "afternoon",
        "item_type": "attraction",
        "placeId": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": ("역사·전통",),
        "isSeed": is_seed,
    }


def _candidate(
    place_id: str,
    title: str,
    latitude: float,
    longitude: float,
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": ("역사·전통",),
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
        "soft_similarity": 0.2,
    }


class _FakePlannerRuntime:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.destination_search = _FakeDestinationSearch(candidates)
        self.embedding = _FakeEmbedding()


class _FakeDestinationSearch:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.candidates = candidates

    def search_candidates(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return self.candidates


class _FakeEmbedding:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(query))]
