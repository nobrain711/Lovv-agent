from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service_types import PlaceScoreResult
from lovv_agent_v2.agents.city_select.scoring.service_validation import (
    mapping_get,
    numeric,
)

EARTH_RADIUS_KM = 6371.0088
USER_DISTANCE_PENALTY_MAX = 0.05
USER_DISTANCE_PENALTY_DAYTRIP = 0.08
USER_DISTANCE_PENALTY_2D1N = 0.04
USER_DISTANCE_PENALTY_LONG_TRIP = 0.0


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    first_lat = math.radians(numeric(lat1, "lat1"))
    first_lon = math.radians(numeric(lon1, "lon1"))
    second_lat = math.radians(numeric(lat2, "lat2"))
    second_lon = math.radians(numeric(lon2, "lon2"))
    delta_lat = second_lat - first_lat
    delta_lon = second_lon - first_lon
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat)
        * math.cos(second_lat)
        * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(haversine))


def city_distance_penalty(
    scored_places: Sequence[PlaceScoreResult],
    user_location: Any | None,
    trip_type: str | None,
) -> float:
    if user_location is None:
        return 0.0
    weight = _distance_penalty_weight(trip_type)
    if weight <= 0.0:
        return 0.0
    origin = _location_pair(user_location)
    if origin is None:
        return 0.0
    coordinates = tuple(
        (place.latitude, place.longitude)
        for place in scored_places
        if place.latitude is not None and place.longitude is not None
    )
    if not coordinates:
        return 0.0
    avg_latitude = sum(item[0] for item in coordinates) / len(coordinates)
    avg_longitude = sum(item[1] for item in coordinates) / len(coordinates)
    distance_km = haversine_distance(origin[0], origin[1], avg_latitude, avg_longitude)
    return weight * min(distance_km / 300.0, 1.0)


def _distance_penalty_weight(trip_type: str | None) -> float:
    match trip_type:
        case "daytrip":
            return USER_DISTANCE_PENALTY_DAYTRIP
        case "2d1n":
            return USER_DISTANCE_PENALTY_2D1N
        case "3d2n" | "4d3n":
            return USER_DISTANCE_PENALTY_LONG_TRIP
        case None:
            return USER_DISTANCE_PENALTY_MAX
        case _:
            return USER_DISTANCE_PENALTY_LONG_TRIP


def _location_pair(location: Any) -> tuple[float, float] | None:
    if isinstance(location, (list, tuple)) and len(location) == 2:
        return (numeric(location[0], "latitude"), numeric(location[1], "longitude"))
    if isinstance(location, Mapping):
        latitude = mapping_get(location, "latitude", "lat", default=None)
        longitude = mapping_get(location, "longitude", "lng", "lon", default=None)
    else:
        latitude = getattr(location, "latitude", getattr(location, "lat", None))
        longitude = getattr(
            location,
            "longitude",
            getattr(location, "lng", getattr(location, "lon", None)),
        )
    if latitude is None or longitude is None:
        return None
    return (numeric(latitude, "latitude"), numeric(longitude, "longitude"))
