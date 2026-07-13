from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

DRIVING_KMH = 60.0


@dataclass(frozen=True, slots=True)
class SnapResponse:
    places: tuple[Mapping[str, object], ...]
    excluded_place_ids: tuple[str, ...]
    audit: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class MatrixResponse:
    durations: Mapping[tuple[str, str], float]
    audit: Mapping[str, object]


class TravelTimeProvider(Protocol):
    def snap_places(
        self,
        places: Sequence[Mapping[str, object]],
        transport_pref: str,
    ) -> SnapResponse: ...

    def matrix_minutes(
        self,
        place_ids: tuple[str, ...],
        transport_pref: str,
    ) -> MatrixResponse: ...


@dataclass(slots=True)
class HaversineTravelTimeProvider:
    places_by_id: dict[str, Mapping[str, object]] = field(default_factory=dict)

    def snap_places(
        self,
        places: Sequence[Mapping[str, object]],
        transport_pref: str,
    ) -> SnapResponse:
        snapped: list[Mapping[str, object]] = []
        excluded: list[str] = []
        self.places_by_id.clear()
        for place in places:
            place_id = _place_id(place)
            if place_id and _coordinate(place, "latitude") is not None and _coordinate(place, "longitude") is not None:
                snapped.append(place)
                self.places_by_id[place_id] = place
            elif place_id:
                excluded.append(place_id)
        return SnapResponse(
            places=tuple(snapped),
            excluded_place_ids=tuple(excluded),
            audit={
                "snap_provider": "haversine",
                "snap_profile": _profile(transport_pref),
                "snap_fallback_used": True,
            },
        )

    def matrix_minutes(
        self,
        place_ids: tuple[str, ...],
        transport_pref: str,
    ) -> MatrixResponse:
        durations: dict[tuple[str, str], float] = {}
        for first in place_ids:
            for second in place_ids:
                durations[(first, second)] = 0.0 if first == second else _duration_between(
                    self.places_by_id.get(first),
                    self.places_by_id.get(second),
                )
        return MatrixResponse(
            durations=durations,
            audit={
                "matrix_provider": "haversine",
                "duration_profile": _profile(transport_pref),
                "duration_unit": "minutes",
                "fallback_used": "haversine_duration",
            },
        )


def _duration_between(
    first: Mapping[str, object] | None,
    second: Mapping[str, object] | None,
) -> float:
    if first is None or second is None:
        return math.inf
    first_lat = _coordinate(first, "latitude")
    first_lon = _coordinate(first, "longitude")
    second_lat = _coordinate(second, "latitude")
    second_lon = _coordinate(second, "longitude")
    if first_lat is None or first_lon is None or second_lat is None or second_lon is None:
        return math.inf
    return _haversine_km(first_lat, first_lon, second_lat, second_lon) / DRIVING_KMH * 60.0


def _haversine_km(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    lat1 = math.radians(first_latitude)
    lat2 = math.radians(second_latitude)
    delta_lat = math.radians(second_latitude - first_latitude)
    delta_lon = math.radians(second_longitude - first_longitude)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _place_id(place: Mapping[str, object]) -> str:
    value = place.get("place_id", place.get("placeId"))
    return value.strip() if isinstance(value, str) else ""


def _coordinate(place: Mapping[str, object], key: str) -> float | None:
    alt_key = "lat" if key == "latitude" else "lon"
    value = place.get(key, place.get(alt_key))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _profile(transport_pref: str) -> str:
    if transport_pref == "walk":
        return "foot-walking"
    if transport_pref in {"transit", "public_transport"}:
        return "driving-car"
    return "driving-car"
