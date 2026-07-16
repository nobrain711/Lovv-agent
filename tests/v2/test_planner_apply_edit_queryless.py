from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_without_query_backfills_from_current_order_city() -> None:
    runtime = _FakePlannerRuntime(_candidate("attraction#new", "새 후보"))

    result = apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(),
            "planner": {"planner_output": _planner_output(), "modify_context": {"reserve_pool": []}},
            "runtime": {"planner_runtime": runtime},
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#new"
    assert runtime.embedding.queries == ["경주시 여행지"]
    assert runtime.destination_search.calls[0]["city_id"] == "KR-47-130"


def _slot_replace_intent() -> dict[str, object]:
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
                    "condition": {"replacement_query": None, "theme": None, "avoid_content_ids": []},
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
        "cityName": "경주시",
        "theme": "역사·전통",
        "latitude": 35.83 + order * 0.001,
        "longitude": 129.21 + order * 0.001,
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": (),
        "recommendation_reasons": (),
        "itinerary_flow_reason": "기존 일정입니다.",
        "external_links": {},
        "confidence": 0.76,
        "user_notice": (),
        "validation_result": {"planner_status_gate": "ok"},
        "alternative_itinerary": (),
    }


def _candidate(place_id: str, title: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": 35.833,
        "longitude": 129.219,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": ("역사·전통",),
        "source": "retrieved",
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
        "soft_similarity": 0.2,
    }


class _FakePlannerRuntime:
    def __init__(self, candidate: dict[str, object]) -> None:
        self.destination_search = _FakeDestinationSearch(candidate)
        self.embedding = _FakeEmbedding()


class _FakeDestinationSearch:
    def __init__(self, candidate: dict[str, object]) -> None:
        self.candidate = candidate
        self.calls: list[dict[str, object]] = []

    def search_candidates(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return [self.candidate]


class _FakeEmbedding:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.1, 0.2]
