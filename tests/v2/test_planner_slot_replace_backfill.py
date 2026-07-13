from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_apply_edit_without_query_backfills_when_reserve_breaks_route() -> None:
    runtime = _FakePlannerRuntime(
        _candidate(
            "attraction#retrieved",
            "검색 보강 후보",
            35.833,
            129.219,
        ),
    )
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
                            "너무 먼 예비 후보",
                            33.45,
                            126.55,
                        ),
                    ],
                },
            },
            "runtime": {"planner_runtime": runtime},
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    assert itinerary[1]["placeId"] == "attraction#retrieved"
    assert runtime.embedding.queries == ["경주시 여행지"]


def _slot_replace_intent() -> dict[str, object]:
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
            "kind": "slot_replace",
            "routing_hint": "planner_apply_edit",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "op": "REPLACE",
                    "target": {"content_id": "attraction#old", "day": 1, "order": 2},
                    "condition": {"replacement_query": None, "theme": "역사·전통", "avoid_content_ids": []},
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
        "validation_result": {"planner_status_gate": "ok"},
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
        "placeId": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
        "city_id": "KR-47-130",
        "city_name_ko": "경주시",
        "theme_tags": ("역사·전통",),
        "isSeed": is_seed,
    }


def _candidate(place_id: str, title: str, latitude: float, longitude: float) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": latitude,
        "longitude": longitude,
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
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(query))]
