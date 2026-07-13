from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from lovv_agent_v2.tools.rds_mysql_rows import SqlParameters, SqlRow
from lovv_agent_v2.tools.saved_itinerary_signals import (
    RdsSavedItinerarySignalsTool,
    RdsSavedItinerarySignalsToolConfig,
)


@dataclass(frozen=True, slots=True)
class SqlCall:
    sql: str
    parameters: SqlParameters


@dataclass(slots=True)
class FakeSqlClient:
    responses: list[list[SqlRow]]
    calls: list[SqlCall] = field(default_factory=list)

    def fetch_all(
        self,
        sql: str,
        parameters: SqlParameters | None = None,
    ) -> list[SqlRow]:
        self.calls.append(SqlCall(sql=sql, parameters=parameters or {}))
        return self.responses.pop(0)


def test_rds_saved_itinerary_tool_fetches_profile_evidence_signals() -> None:
    client = FakeSqlClient(
        responses=[
            [{"saved_trip_count": 4}],
            [
                {
                    "id": "itn-1",
                    "destination_json": '{"country":"KR","city":"Gangneung"}',
                    "themes_json": '["sea_coast","nature_trekking"]',
                    "preference_snapshot": '{"pace":"slow"}',
                    "trip_type": "3d2n",
                    "duration_label": "3 days 2 nights",
                    "conditions_snapshot_json": '{"transport_pref":"car"}',
                    "itinerary_json": '{"days":[{"day":1,"items":[{"title":"fallback"}]}]}',
                },
            ],
            [
                {
                    "id": "itn-liked",
                    "destination_json": '{"country":"KR","city":"Sokcho"}',
                    "themes_json": '["sea_coast"]',
                    "preference_snapshot": "{}",
                    "trip_type": "daytrip",
                    "duration_label": "day trip",
                    "conditions_snapshot_json": "{}",
                    "itinerary_json": '{"days":[]}',
                },
            ],
            [
                {
                    "itinerary_id": "itn-1",
                    "day_index": 1,
                    "sort_order": 2,
                    "place_name": "Anmok Beach",
                    "content_id": "CID-1",
                    "place_id": "PLC-1",
                },
            ],
        ],
    )
    tool = RdsSavedItinerarySignalsTool(sql_client=client)

    signals = tool.fetch_saved_itinerary_signals(
        actor_id="user-1",
        thread_id="thread-1",
        recent_limit=3,
        liked_limit=2,
    )

    assert signals["saved_trip_count"] == 4
    assert signals["source"] == "rds_mysql_saved_itinerary_signals_tool"
    recent_itineraries = signals["recent_itineraries"]
    liked_itineraries = signals["liked_itineraries"]
    assert isinstance(recent_itineraries, list)
    assert isinstance(liked_itineraries, list)
    assert recent_itineraries == [
        {
            "itinerary_id": "itn-1",
            "destination_json": {"country": "KR", "city": "Gangneung"},
            "themes_json": ["sea_coast", "nature_trekking"],
            "preference_snapshot": {"pace": "slow"},
            "trip_type": "3d2n",
            "duration_label": "3 days 2 nights",
            "conditions_snapshot_json": {"transport_pref": "car"},
            "items": [
                {
                    "place_name": "Anmok Beach",
                    "content_id": "CID-1",
                    "place_id": "PLC-1",
                    "day_index": 1,
                    "sort_order": 2,
                },
            ],
        },
    ]
    liked_itinerary = liked_itineraries[0]
    assert isinstance(liked_itinerary, dict)
    assert liked_itinerary["itinerary_id"] == "itn-liked"
    assert liked_itinerary["reaction"] == "like"
    assert "FROM itineraries" in client.calls[1].sql
    assert "JOIN plan_reactions" in client.calls[2].sql
    assert "FROM itinerary_items" in client.calls[3].sql
    assert client.calls[1].parameters == {"actor_id": "user-1", "limit": 3}


def test_rds_saved_itinerary_tool_falls_back_to_snapshot_items() -> None:
    client = FakeSqlClient(
        responses=[
            [{"saved_trip_count": 1}],
            [
                {
                    "id": "itn-1",
                    "destination_json": "{}",
                    "themes_json": "[]",
                    "preference_snapshot": "{}",
                    "trip_type": "daytrip",
                    "duration_label": "day trip",
                    "conditions_snapshot_json": "{}",
                    "itinerary_json": (
                        '{"days":[{"day":1,"stops":[{"title":"Gyeongpo Lake",'
                        '"contentId":"CID-2","placeId":"PLC-2"}]}]}'
                    ),
                },
            ],
            [],
            [],
        ],
    )
    tool = RdsSavedItinerarySignalsTool(sql_client=client)

    signals = tool.fetch_saved_itinerary_signals(
        actor_id="user-1",
        thread_id="thread-1",
        recent_limit=5,
        liked_limit=5,
    )

    recent_itineraries = signals["recent_itineraries"]
    assert isinstance(recent_itineraries, list)
    recent_itinerary = recent_itineraries[0]
    assert isinstance(recent_itinerary, dict)
    assert recent_itinerary["items"] == [
        {
            "place_name": "Gyeongpo Lake",
            "content_id": "CID-2",
            "place_id": "PLC-2",
            "day_index": 1,
            "sort_order": 1,
        },
    ]


def test_rds_saved_itinerary_tool_rejects_unsafe_table_names() -> None:
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        RdsSavedItinerarySignalsToolConfig(itineraries_table="itineraries; DROP TABLE users")
