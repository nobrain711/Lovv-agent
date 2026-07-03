from __future__ import annotations

from lovv_agent_v2.agents.city_select.tools import build_attraction_filter


def test_filter_combines_preferred_and_disliked_city_ids() -> None:
    metadata_filter = build_attraction_filter(
        theme="history",
        preferred_city_ids=("KR-47-130", "KR-51-730"),
        disliked_city_ids=("KR-11-000",),
    )

    assert metadata_filter == {
        "$and": [
            {"entity_type": {"$eq": "attraction"}},
            {"city_id": {"$in": ["KR-47-130", "KR-51-730"]}},
            {"city_id": {"$ne": "KR-11-000"}},
            {"theme_tags": {"$eq": "history"}},
        ],
    }
