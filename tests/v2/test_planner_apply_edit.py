from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_replaces_one_slot_from_reserve_pool() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate(
                            "attraction#new",
                            "경주 숲길",
                            35.833,
                            129.219,
                        ),
                    ],
                },
            },
        },
    )

    planner = result["planner"]
    itinerary = planner["planner_output"]["itinerary"]
    assert [item["title"] for item in itinerary] == ["경주 교촌마을", "경주 숲길", "육부전"]
    assert itinerary[1]["day"] == 1
    assert itinerary[1]["order"] == 2
    assert planner["modify_context"]["applied_edit"]["replacement"]["content_id"] == "attraction#new"


def test_apply_edit_fails_when_all_candidates_break_hard_leg_limit() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate(
                            "attraction#far",
                            "너무 먼 장소",
                            33.45,
                            126.55,
                        ),
                    ],
                },
            },
        },
    )

    failed = result["planner"]["modify_context"]["failed_edit"]
    assert failed["reason_code"] == "slot_replace_route_infeasible"
    assert failed["failed_route_candidate_count"] == 1


def test_apply_edit_with_query_uses_retrieval_before_old_reserve_pool() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(
                replacement_query="조용한 숲길",
                theme="자연·트레킹",
            ),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate(
                            "attraction#reserve",
                            "이전 예비 후보",
                            35.833,
                            129.219,
                        ),
                    ],
                },
            },
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    _candidate(
                        "attraction#retrieved",
                        "검색된 숲길",
                        35.833,
                        129.219,
                        theme="자연·트레킹",
                    ),
                ),
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#retrieved"


def test_apply_edit_with_query_does_not_hard_filter_retrieval_by_theme() -> None:
    runtime = _FakePlannerRuntime(
        _candidate(
            "attraction#retrieved",
            "검색된 후보",
            35.833,
            129.219,
            theme="예술·감성",
        ),
    )
    apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(
                replacement_query="감성적인 전시 공간",
                theme="예술·감성",
            ),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {"planner_runtime": runtime},
        },
    )

    assert runtime.destination_search.calls[0]["theme"] is None


def test_apply_edit_with_query_excludes_existing_itinerary_items() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(replacement_query="사진 찍기 좋은 곳"),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    [
                        _candidate(
                            "attraction#seed",
                            "기존 1순위 장소",
                            35.8296,
                            129.2147,
                        ),
                        _candidate(
                            "attraction#new",
                            "새 후보",
                            35.833,
                            129.219,
                        ),
                    ],
                ),
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#new"


def _slot_replace_intent(
    *,
    replacement_query: str | None = None,
    theme: str | None = "역사·전통",
) -> dict[str, object]:
    return {
        "intent_type": "modification",
        "city_select_input": {
            "country": "KR",
            "travel_month": 10,
            "trip_type": "2d1n",
            "active_required_themes": ("역사·전통",),
            "destination_id": "KR-47-130",
            "include_festivals": False,
        },
        "modify_intent": {
            "status": "ok",
            "kind": "slot_replace",
            "routing_hint": "planner_apply_edit",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {
                        "item_id": "item-2",
                        "content_id": "attraction#old",
                        "day": 1,
                        "order": 2,
                    },
                    "condition": {
                        "replacement_query": replacement_query,
                        "theme": theme,
                        "avoid_content_ids": ["attraction#old"],
                    },
                    "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
                },
            ],
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
            _order_item("item-2", "attraction#old", "경주 계림", 1, 2, 35.8326, 129.2190, False),
            _order_item("item-3", "attraction#third", "육부전", 1, 3, 35.8170, 129.2144, False),
        ],
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": [
            _planner_item("attraction#seed", "경주 교촌마을", 1, 1, 35.8296, 129.2147, True),
            _planner_item("attraction#old", "경주 계림", 1, 2, 35.8326, 129.2190, False),
            _planner_item("attraction#third", "육부전", 1, 3, 35.8170, 129.2144, False),
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
        "body": "기존 설명입니다.",
        "reason": "기존 이유입니다.",
        "moveMinutes": 0,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": ("역사·전통",),
        "source": "test",
        "isSeed": is_seed,
        "reason_code": "seed_floor" if is_seed else "relevance_quota",
        "evidence": {"similarity": 0.8, "soft_similarity": 0.0, "themes": ("역사·전통",)},
    }


def _candidate(
    place_id: str,
    title: str,
    latitude: float,
    longitude: float,
    *,
    theme: str = "역사·전통",
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": (theme,),
        "source": "reserve",
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
        "soft_similarity": 0.2,
    }


class _FakePlannerRuntime:
    def __init__(self, candidates: dict[str, object] | list[dict[str, object]]) -> None:
        self.destination_search = _FakeDestinationSearch(candidates)
        self.embedding = _FakeEmbedding()


class _FakeDestinationSearch:
    def __init__(self, candidates: dict[str, object] | list[dict[str, object]]) -> None:
        self.candidates = [candidates] if isinstance(candidates, dict) else candidates
        self.calls: list[dict[str, object]] = []

    def search_candidates(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return self.candidates


class _FakeEmbedding:
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2]
