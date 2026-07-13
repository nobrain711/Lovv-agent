from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_with_query_without_theme_keeps_retrieval_order() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    [
                        _candidate("attraction#off-theme", "검색 상위 후보", "미식·노포"),
                        _candidate("attraction#active-theme", "활성 테마 후보", "자연·트레킹"),
                    ],
                ),
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#off-theme"


def test_apply_edit_with_query_prefers_condition_theme_only() -> None:
    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(theme="예술·감성"),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {
                "planner_runtime": _FakePlannerRuntime(
                    [
                        _candidate("attraction#active-theme", "활성 테마 후보", "자연·트레킹"),
                        _candidate("attraction#condition-theme", "조건 테마 후보", "예술·감성"),
                    ],
                ),
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#condition-theme"


def _slot_replace_intent(*, replacement_query: str | None = "조금 더 한적한 곳", theme: str | None = None) -> dict[str, object]:
    return {
        "intent_type": "modification",
        "city_select_input": {
            "country": "KR",
            "travel_month": 10,
            "trip_type": "2d1n",
            "active_required_themes": ("자연·트레킹", "역사·전통"),
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
                    "target": {"content_id": "attraction#old", "day": 1, "order": 2},
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
            _order_item("item-1", "attraction#seed", "경주 교촌마을", 1, 1, True),
            _order_item("item-2", "attraction#old", "경주 계림", 1, 2, False),
            _order_item("item-3", "attraction#third", "육부전", 1, 3, False),
        ],
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": [
            _planner_item("attraction#seed", "경주 교촌마을", 1, 1, True),
            _planner_item("attraction#old", "경주 계림", 1, 2, False),
            _planner_item("attraction#third", "육부전", 1, 3, False),
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


def _candidate(place_id: str, title: str, theme: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": 35.833,
        "longitude": 129.219,
        "city_id": "KR-47-130",
        "theme_tags": (theme,),
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
    }


class _FakePlannerRuntime:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.destination_search = _FakeDestinationSearch(candidates)
        self.embedding = _FakeEmbedding()


class _FakeDestinationSearch:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self.candidates = candidates

    def search_candidates(self, *args, **kwargs):
        return self.candidates


class _FakeEmbedding:
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2]
