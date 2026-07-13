from __future__ import annotations

from collections.abc import Mapping, Sequence


DEFAULT_FESTIVAL_THEME = "축제·이벤트"


def festival_seed_places(
    state: Mapping[str, object],
    selected_city: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    result = _festival_gate_result(state)
    if result is None or result.get("status") != "ok":
        return ()

    places: list[dict[str, object]] = []
    for city in _mapping_sequence(result.get("verified_festival_cities")):
        if not _matches_selected_city(city, selected_city):
            continue
        for festival in _mapping_sequence(city.get("festivals")):
            payload = _festival_place_payload(city, festival, selected_city)
            if payload is not None:
                places.append(payload)
    return tuple(places)


def festival_seed_refs(
    state: Mapping[str, object],
    selected_city: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "place_id": place["place_id"],
            "festival_id": place["festival_id"],
            "theme": place.get("assigned_theme", DEFAULT_FESTIVAL_THEME),
            "must_include": True,
        }
        for place in festival_seed_places(state, selected_city)
    )


def _festival_gate_result(state: Mapping[str, object]) -> Mapping[str, object] | None:
    festival_gate = state.get("festival_gate")
    if not isinstance(festival_gate, Mapping):
        return None
    result = festival_gate.get("result")
    return result if isinstance(result, Mapping) else None


def _matches_selected_city(
    city: Mapping[str, object],
    selected_city: Mapping[str, object],
) -> bool:
    city_ids = _candidate_values(city, ("city_id", "destination_id"))
    city_keys = _candidate_values(city, ("ddb_pk", "city_key", "PK", "pk"))
    selected_ids = _candidate_values(selected_city, ("city_id", "destination_id"))
    selected_keys = _candidate_values(selected_city, ("ddb_pk", "city_key", "PK", "pk"))
    return bool(city_ids.intersection(selected_ids) or city_keys.intersection(selected_keys))


def _festival_place_payload(
    city: Mapping[str, object],
    festival: Mapping[str, object],
    selected_city: Mapping[str, object],
) -> dict[str, object] | None:
    festival_id = _text(_first_present(festival, ("festival_id", "festivalId", "id")))
    title = _text(_first_present(festival, ("name", "title")))
    if festival_id is None or title is None:
        return None

    theme_tags = _theme_tags(festival)
    assigned_theme = _text(festival.get("assigned_theme")) or theme_tags[0]
    city_id = _text(_first_present(festival, ("city_id", "destination_id"))) or _text(
        _first_present(city, ("city_id", "destination_id")),
    ) or _text(_first_present(selected_city, ("city_id", "destination_id")))
    city_name = _text(
        _first_present(
            festival,
            ("city_name_ko", "city_name", "cityName", "cityNameKo"),
        ),
    ) or _text(_first_present(city, ("city_name_ko", "city_name", "cityName")))
    ddb_pk = _text(_first_present(festival, ("ddb_pk", "city_key", "PK", "pk"))) or _text(
        _first_present(city, ("ddb_pk", "city_key", "PK", "pk")),
    ) or _text(_first_present(selected_city, ("ddb_pk", "city_key", "PK", "pk")))
    ddb_sk = _text(_first_present(festival, ("ddb_sk", "SK", "sk")))
    latitude, longitude = _coordinates(festival)

    payload: dict[str, object] = {
        "place_id": f"festival#{festival_id}",
        "festival_id": festival_id,
        "festivalId": festival_id,
        "title": title,
        "item_type": "festival",
        "theme_tags": theme_tags,
        "assigned_theme": assigned_theme,
        "city_id": city_id,
        "city_name_ko": city_name,
        "ddb_pk": ddb_pk,
        "ddb_sk": ddb_sk,
        "source": _text(festival.get("source")) or "dynamodb",
        "date_status": _text(festival.get("date_status")) or "confirmed",
        "event_start_date": _text(_first_present(festival, ("event_start_date", "start_date"))),
        "event_end_date": _text(_first_present(festival, ("event_end_date", "end_date"))),
        "score_audit": {"score_components": {"raw_similarity": 1.0}},
        "soft_similarity": 1.0,
        "sim": 1.0,
    }
    if latitude is not None and longitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    return payload


def _coordinates(festival: Mapping[str, object]) -> tuple[float | None, float | None]:
    raw = festival.get("raw")
    raw_mapping = raw if isinstance(raw, Mapping) else {}
    latitude = _float(_first_present(festival, ("latitude", "lat", "mapy", "y")))
    longitude = _float(_first_present(festival, ("longitude", "lon", "lng", "mapx", "x")))
    if latitude is None:
        latitude = _float(_first_present(raw_mapping, ("latitude", "lat", "mapy", "y")))
    if longitude is None:
        longitude = _float(_first_present(raw_mapping, ("longitude", "lon", "lng", "mapx", "x")))
    return latitude, longitude


def _theme_tags(festival: Mapping[str, object]) -> tuple[str, ...]:
    tags = _string_tuple(_first_present(festival, ("theme_tags", "themeTags", "themes")))
    if tags:
        return tags
    assigned_theme = _text(festival.get("assigned_theme"))
    if assigned_theme is not None:
        return (assigned_theme,)
    return (DEFAULT_FESTIVAL_THEME,)


def _candidate_values(
    payload: Mapping[str, object],
    keys: Sequence[str],
) -> set[str]:
    return {
        value
        for key in keys
        if (value := _text(payload.get(key))) is not None
    }


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in (_text(item) for item in value) if item is not None)


def _first_present(payload: Mapping[str, object], keys: Sequence[str]) -> object:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
