from __future__ import annotations

from collections.abc import Mapping


def durations_minutes(result) -> dict[tuple[str, str], float]:
    durations: dict[tuple[str, str], float] = {}
    for row_index, source_id in enumerate(result.place_ids):
        for column_index, destination_id in enumerate(result.place_ids):
            duration_sec = result.durations_sec[row_index][column_index]
            durations[(source_id, destination_id)] = (
                0.0 if duration_sec is None else float(duration_sec) / 60.0
            )
    return durations


def snapped_payloads(
    payload_by_id: Mapping[str, Mapping[str, object]],
    result,
) -> dict[str, Mapping[str, object]]:
    payloads: dict[str, Mapping[str, object]] = {}
    for original, snapped, distance_m, road_name in zip(
        result.original_places,
        result.snapped_places,
        result.snapped_distances_m,
        result.road_names,
        strict=True,
    ):
        payloads[original.place_id] = {
            **payload_by_id[original.place_id],
            "latitude": snapped.lat,
            "longitude": snapped.lon,
            "ors_snapped_distance_m": distance_m,
            "ors_road_name": road_name,
        }
    return payloads


__all__ = ["durations_minutes", "snapped_payloads"]
