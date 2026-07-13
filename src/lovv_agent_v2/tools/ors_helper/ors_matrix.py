from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ORS_API_BASE = "https://api.openrouteservice.org"
EARTH_RADIUS_KM = 6371.0088
DRIVING_KMH = 60.0

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class OrsMatrixError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    place_id: str
    title: str
    lat: float
    lon: float
    theme_tags: list[str] | None = None
    subtype: str | None = None
    source_tier: str | None = None


@dataclass(frozen=True, slots=True)
class SnapResult:
    profile: str
    original_places: tuple[PlaceCandidate, ...]
    snapped_places: tuple[PlaceCandidate, ...]
    snapped_distances_m: tuple[float, ...]
    road_names: tuple[str, ...]
    fallback_used: bool
    source: str


@dataclass(frozen=True, slots=True)
class MatrixResult:
    profile: str
    place_ids: tuple[str, ...]
    durations_sec: tuple[tuple[float | None, ...], ...]
    fallback_used: bool
    source: str


@dataclass(frozen=True, slots=True)
class OrsMatrixClient:
    timeout_sec: int = 20
    cache_dir: Path | None = None

    def snap_places(
        self,
        places: Sequence[PlaceCandidate],
        profile: str,
        radius_m: float = 300.0,
    ) -> SnapResult:
        original_places = tuple(places)
        if not original_places:
            return _snap_result(profile, original_places, (), (), (), False, "ors_empty")
        try:
            payload: dict[str, JsonValue] = {
                "locations": _locations(original_places),
                "radius": radius_m,
            }
            response = _post_json(
                f"/v2/snap/{profile}",
                payload,
                self.timeout_sec,
            )
            return _parse_snap_response(profile, original_places, response)
        except (OrsMatrixError, OSError, TimeoutError, ValueError, TypeError, KeyError):
            return _snap_fallback(profile, original_places)

    def get_matrix(
        self,
        places: Sequence[PlaceCandidate],
        profile: str,
        use_cache: bool = True,
        allow_fallback: bool = True,
    ) -> MatrixResult:
        matrix_places = tuple(places)
        if not matrix_places:
            return MatrixResult(profile, (), (), False, "ors_empty")
        try:
            metrics: list[JsonValue] = ["duration"]
            payload: dict[str, JsonValue] = {
                "locations": _locations(matrix_places),
                "metrics": metrics,
                "units": "m",
            }
            response = _post_json(
                f"/v2/matrix/{profile}",
                payload,
                self.timeout_sec,
            )
            return _parse_matrix_response(profile, matrix_places, response)
        except (OrsMatrixError, OSError, TimeoutError, ValueError, TypeError, KeyError):
            if allow_fallback:
                return _matrix_fallback(profile, matrix_places)
            raise


def load_env_local(env_file: str) -> None:
    path = Path(env_file)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip("\"'")


def _post_json(path: str, payload: dict[str, JsonValue], timeout_sec: int) -> JsonValue:
    api_key = os.getenv("ORS_API_KEY")
    if not api_key:
        raise OrsMatrixError("ORS_API_KEY is required")
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{ORS_API_BASE}{path}",
        data=data,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OrsMatrixError("ORS request failed") from exc


def _parse_snap_response(
    profile: str,
    original_places: tuple[PlaceCandidate, ...],
    response: JsonValue,
) -> SnapResult:
    if not isinstance(response, dict):
        raise OrsMatrixError("ORS snap response must be an object")
    locations = response.get("locations")
    if not isinstance(locations, list):
        raise OrsMatrixError("ORS snap response missing locations")
    snapped: list[PlaceCandidate] = []
    distances: list[float] = []
    road_names: list[str] = []
    for original, item in zip(original_places, locations, strict=True):
        coordinate = _location_coordinate(item)
        snapped.append(
            PlaceCandidate(
                place_id=original.place_id,
                title=original.title,
                lat=coordinate[1],
                lon=coordinate[0],
                theme_tags=original.theme_tags,
                subtype=original.subtype,
                source_tier=original.source_tier,
            ),
        )
        distances.append(_snap_distance(item))
        road_names.append(_road_name(item))
    return _snap_result(
        profile,
        original_places,
        tuple(snapped),
        tuple(distances),
        tuple(road_names),
        False,
        "ors",
    )


def _parse_matrix_response(
    profile: str,
    places: tuple[PlaceCandidate, ...],
    response: JsonValue,
) -> MatrixResult:
    if not isinstance(response, dict):
        raise OrsMatrixError("ORS matrix response must be an object")
    durations = response.get("durations")
    if not isinstance(durations, list):
        raise OrsMatrixError("ORS matrix response missing durations")
    parsed_rows = tuple(_duration_row(row) for row in durations)
    return MatrixResult(profile, tuple(place.place_id for place in places), parsed_rows, False, "ors")


def _snap_fallback(profile: str, places: tuple[PlaceCandidate, ...]) -> SnapResult:
    return _snap_result(
        profile,
        places,
        places,
        tuple(0.0 for _ in places),
        tuple("" for _ in places),
        True,
        "ors_haversine",
    )


def _matrix_fallback(profile: str, places: tuple[PlaceCandidate, ...]) -> MatrixResult:
    rows = tuple(
        tuple(0.0 if first.place_id == second.place_id else _duration_sec(first, second) for second in places)
        for first in places
    )
    return MatrixResult(profile, tuple(place.place_id for place in places), rows, True, "ors_haversine")


def _snap_result(
    profile: str,
    original_places: tuple[PlaceCandidate, ...],
    snapped_places: tuple[PlaceCandidate, ...],
    snapped_distances_m: tuple[float, ...],
    road_names: tuple[str, ...],
    fallback_used: bool,
    source: str,
) -> SnapResult:
    return SnapResult(
        profile=profile,
        original_places=original_places,
        snapped_places=snapped_places,
        snapped_distances_m=snapped_distances_m,
        road_names=road_names,
        fallback_used=fallback_used,
        source=source,
    )


def _locations(places: Sequence[PlaceCandidate]) -> list[JsonValue]:
    return [[place.lon, place.lat] for place in places]


def _location_coordinate(value: JsonValue) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise OrsMatrixError("ORS snap location must be an object")
    location = value.get("location")
    if not isinstance(location, list) or len(location) < 2:
        raise OrsMatrixError("ORS snap location missing coordinate")
    lon = _number(location[0])
    lat = _number(location[1])
    return lon, lat


def _snap_distance(value: JsonValue) -> float:
    if not isinstance(value, dict):
        return 0.0
    distance = value.get("snapped_distance", value.get("distance", 0.0))
    return _number(distance)


def _road_name(value: JsonValue) -> str:
    if not isinstance(value, dict):
        return ""
    name = value.get("name", value.get("road_name", ""))
    return name if isinstance(name, str) else ""


def _duration_row(row: JsonValue) -> tuple[float | None, ...]:
    if not isinstance(row, list):
        raise OrsMatrixError("ORS matrix row must be a list")
    return tuple(None if item is None else _number(item) for item in row)


def _duration_sec(first: PlaceCandidate, second: PlaceCandidate) -> float:
    return _haversine_km(first.lat, first.lon, second.lat, second.lon) / DRIVING_KMH * 3600.0


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
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _number(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrsMatrixError("ORS numeric value is invalid")
    return float(value)
