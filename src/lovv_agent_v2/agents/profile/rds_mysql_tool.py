from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lovv_agent_v2.agents.profile.rds_mysql_rows import (
    JsonValue,
    SqlParameters,
    SqlRow,
    bounded_limit,
    empty_signals,
    evidence_itinerary,
    item_from_row,
    itinerary_ids,
    positive_int,
    require_safe_identifier,
    text,
)

_DEFAULT_MAX_LIMIT = 50


class SqlFetchClient(Protocol):
    def fetch_all(self, sql: str, parameters: SqlParameters | None = None) -> Sequence[SqlRow]:
        ...


@dataclass(frozen=True, slots=True)
class RdsSavedItinerarySignalsToolConfig:
    itineraries_table: str = "itineraries"
    itinerary_items_table: str = "itinerary_items"
    plan_reactions_table: str = "plan_reactions"
    max_limit: int = _DEFAULT_MAX_LIMIT

    def __post_init__(self) -> None:
        for identifier in (
            self.itineraries_table,
            self.itinerary_items_table,
            self.plan_reactions_table,
        ):
            require_safe_identifier(identifier)
        if self.max_limit < 1:
            raise ValueError("max_limit must be positive")


@dataclass(frozen=True, slots=True)
class RdsSavedItinerarySignalsTool:
    sql_client: SqlFetchClient
    config: RdsSavedItinerarySignalsToolConfig = field(
        default_factory=RdsSavedItinerarySignalsToolConfig,
    )

    def fetch_saved_itinerary_signals(
        self,
        *,
        actor_id: str,
        thread_id: str,
        recent_limit: int,
        liked_limit: int,
    ) -> dict[str, JsonValue]:
        user_id = actor_id.strip()
        if not user_id:
            return empty_signals()

        saved_trip_count = _saved_trip_count(self.sql_client, self.config, user_id)
        recent_rows = self.sql_client.fetch_all(
            _recent_itinerary_sql(self.config),
            {"actor_id": user_id, "limit": bounded_limit(recent_limit, self.config.max_limit)},
        )
        liked_rows = self.sql_client.fetch_all(
            _liked_itinerary_sql(self.config),
            {"actor_id": user_id, "limit": bounded_limit(liked_limit, self.config.max_limit)},
        )
        items_by_itinerary = _fetch_items_by_itinerary(
            self.sql_client,
            self.config,
            itinerary_ids(recent_rows, liked_rows),
        )

        return {
            "source": "rds_mysql_saved_itinerary_signals_tool",
            "saved_trip_count": saved_trip_count,
            "recent_itineraries": [
                evidence_itinerary(row, items_by_itinerary, reaction=None)
                for row in recent_rows
            ],
            "liked_itineraries": [
                evidence_itinerary(row, items_by_itinerary, reaction="like")
                for row in liked_rows
            ],
        }


def _saved_trip_count(
    sql_client: SqlFetchClient,
    config: RdsSavedItinerarySignalsToolConfig,
    actor_id: str,
) -> int:
    rows = sql_client.fetch_all(
        "SELECT COUNT(*) AS saved_trip_count "
        f"FROM {config.itineraries_table} "
        "WHERE user_id = :actor_id "
        "AND deleted_at IS NULL",
        {"actor_id": actor_id},
    )
    if not rows:
        return 0
    return positive_int(rows[0].get("saved_trip_count"), 0)


def _recent_itinerary_sql(config: RdsSavedItinerarySignalsToolConfig) -> str:
    return (
        "SELECT id, destination_json, themes_json, preference_snapshot, trip_type, "
        "duration_label, conditions_snapshot_json, itinerary_json "
        f"FROM {config.itineraries_table} "
        "WHERE user_id = :actor_id "
        "AND deleted_at IS NULL "
        "ORDER BY saved_at DESC "
        "LIMIT :limit"
    )


def _liked_itinerary_sql(config: RdsSavedItinerarySignalsToolConfig) -> str:
    return (
        "SELECT i.id, i.destination_json, i.themes_json, i.preference_snapshot, i.trip_type, "
        "i.duration_label, i.conditions_snapshot_json, i.itinerary_json "
        f"FROM {config.itineraries_table} i "
        f"JOIN {config.plan_reactions_table} pr "
        "ON pr.itinerary_id = i.id "
        "AND pr.user_id = i.user_id "
        "AND pr.reaction_type = 'like' "
        "WHERE i.user_id = :actor_id "
        "AND i.deleted_at IS NULL "
        "ORDER BY pr.updated_at DESC, i.saved_at DESC "
        "LIMIT :limit"
    )


def _fetch_items_by_itinerary(
    sql_client: SqlFetchClient,
    config: RdsSavedItinerarySignalsToolConfig,
    itinerary_ids: tuple[str, ...],
) -> dict[str, tuple[dict[str, JsonValue], ...]]:
    if not itinerary_ids:
        return {}

    parameters = {f"itinerary_id_{index}": itinerary_id for index, itinerary_id in enumerate(itinerary_ids)}
    placeholders = ", ".join(f":itinerary_id_{index}" for index in range(len(itinerary_ids)))
    rows = sql_client.fetch_all(
        "SELECT itinerary_id, day_index, sort_order, place_name, content_id, place_id "
        f"FROM {config.itinerary_items_table} "
        f"WHERE itinerary_id IN ({placeholders}) "
        "ORDER BY itinerary_id ASC, day_index ASC, sort_order ASC",
        parameters,
    )
    grouped: dict[str, list[dict[str, JsonValue]]] = {}
    for row in rows:
        itinerary_id = text(row.get("itinerary_id"))
        if itinerary_id is None:
            continue
        grouped.setdefault(itinerary_id, []).append(item_from_row(row))
    return {key: tuple(value) for key, value in grouped.items()}


__all__ = [
    "RdsSavedItinerarySignalsTool",
    "RdsSavedItinerarySignalsToolConfig",
    "SqlFetchClient",
]
