from __future__ import annotations

from lovv_agent_v2.agents.response_packager.itinerary_item_payload import (
    build_itinerary_item_payload,
)
from lovv_agent_v2.tools.destination_policy import normalize_attraction_candidate


def test_attraction_candidate_exposes_source_from_vector_metadata() -> None:
    candidate = normalize_attraction_candidate(
        {
            "key": "attraction#1#0",
            "distance": 0.2,
            "metadata": {
                "entity_type": "attraction",
                "city_id": "KR-TEST",
                "title": "해변",
                "theme_tags": ["바다·해안"],
                "source": "tourapi",
            },
        },
    )

    payload = candidate.to_dict()

    assert payload["source"] == "tourapi"


def test_itinerary_item_payload_maps_source_to_public_source_type() -> None:
    payload = build_itinerary_item_payload(
        {
            "day": 1,
            "order": 1,
            "placeId": "attraction#1",
            "title": "해변",
            "source": "attraction",
            "details": {"source_type": "tourapi"},
        },
        sort_order=1,
    )

    assert payload["sourceType"] == "tourapi"
