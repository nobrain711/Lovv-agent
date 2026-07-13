from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_applies_multiple_slots_in_same_day() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(("op-1", 1, 2), ("op-2", 1, 3)),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "첫 교체 후보"),
                        _candidate("attraction#new-2", "둘째 교체 후보"),
                    ],
                },
            },
        },
    )

    planner = result["planner"]
    itinerary = planner["planner_output"]["itinerary"]
    assert [item["title"] for item in itinerary] == ["경주 교촌마을", "첫 교체 후보", "둘째 교체 후보"]
    assert [edit["op_id"] for edit in planner["modify_context"]["applied_edits"]] == ["op-1", "op-2"]
    assert planner["modify_context"]["applied_edits"][0]["replacement"]["content_id"] != (
        planner["modify_context"]["applied_edits"][1]["replacement"]["content_id"]
    )


def test_apply_edit_applies_slots_across_days() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(
                _order_item("item-1", "attraction#seed", "경주 교촌마을", 1, 1, True),
                _order_item("item-2", "attraction#old-1", "경주 계림", 1, 2, False),
                _order_item("item-3", "attraction#old-2", "육부전", 2, 1, False),
            ),
            "intent": _slot_replace_intent(("op-1", 1, 2), ("op-2", 2, 1)),
            "planner": {
                "planner_output": _planner_output(
                    _planner_item("attraction#seed", "경주 교촌마을", 1, 1, True),
                    _planner_item("attraction#old-1", "경주 계림", 1, 2, False),
                    _planner_item("attraction#old-2", "육부전", 2, 1, False),
                ),
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "첫 교체 후보"),
                        _candidate("attraction#new-2", "둘째 교체 후보"),
                    ],
                },
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert [(item["day"], item["order"], item["title"]) for item in itinerary] == [
        (1, 1, "경주 교촌마을"),
        (1, 2, "첫 교체 후보"),
        (2, 1, "둘째 교체 후보"),
    ]


def test_apply_edit_handles_mixed_query_and_reserve_operations() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(
                ("op-query", 1, 2, "조용한 역사 산책"),
                ("op-reserve", 1, 3, None),
            ),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [_candidate("attraction#reserve", "예비 후보")],
                },
            },
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    _candidate("attraction#retrieved", "검색 후보"),
                ),
            },
        },
    )

    planner = result["planner"]
    itinerary = planner["planner_output"]["itinerary"]
    assert [item["title"] for item in itinerary] == ["경주 교촌마을", "검색 후보", "예비 후보"]
    assert [edit["replacement"]["content_id"] for edit in planner["modify_context"]["applied_edits"]] == [
        "attraction#retrieved",
        "attraction#reserve",
    ]


def _slot_replace_intent(*ops: tuple[str, int, int] | tuple[str, int, int, str | None]) -> dict[str, object]:
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
            "edit_ops": [_operation(*op) for op in ops],
        },
    }


def _operation(op_id: str, day: int, order: int, replacement_query: str | None = None) -> dict[str, object]:
    return {
        "op_id": op_id,
        "op": "REPLACE",
        "target": {"day": day, "order": order},
        "condition": {"replacement_query": replacement_query, "theme": "역사·전통", "avoid_content_ids": []},
        "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
    }


def _request_current_order(*items: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "REQ-MULTI",
        "country": "KR",
        "travel_month": 10,
        "trip_type": "2d1n",
        "destinationId": "KR-47-130",
        "currentOrder": list(items) if items else [
            _order_item("item-1", "attraction#seed", "경주 교촌마을", 1, 1, True),
            _order_item("item-2", "attraction#old-1", "경주 계림", 1, 2, False),
            _order_item("item-3", "attraction#old-2", "육부전", 1, 3, False),
        ],
    }


def _planner_output(*items: dict[str, object]) -> dict[str, object]:
    return {
        "itinerary": list(items) if items else [
            _planner_item("attraction#seed", "경주 교촌마을", 1, 1, True),
            _planner_item("attraction#old-1", "경주 계림", 1, 2, False),
            _planner_item("attraction#old-2", "육부전", 1, 3, False),
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
        "latitude": 35.833,
        "longitude": 129.219,
    }


def _planner_item(
    place_id: str,
    title: str,
    day: int,
    order: int,
    is_seed: bool,
) -> dict[str, object]:
    return {
        "day": day,
        "order": order,
        "placeId": place_id,
        "title": title,
        "latitude": 35.833,
        "longitude": 129.219,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "isSeed": is_seed,
        "reason_code": "seed_floor" if is_seed else "relevance_quota",
    }


def _candidate(place_id: str, title: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": 35.833,
        "longitude": 129.219,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
    }


class _FakePlannerRuntime:
    def __init__(self, candidate: dict[str, object]) -> None:
        self.destination_search = _FakeDestinationSearch(candidate)
        self.embedding = _FakeEmbedding()


class _FakeDestinationSearch:
    def __init__(self, candidate: dict[str, object]) -> None:
        self.candidate = candidate

    def search_candidates(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [self.candidate]


class _FakeEmbedding:
    def embed_query(self, query: str) -> list[float]:
        return [float(len(query))]
