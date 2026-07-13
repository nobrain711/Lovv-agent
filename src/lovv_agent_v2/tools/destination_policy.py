from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.tools.city_select_contracts import (
    ANCHORED_PLACE_SEARCH_MODE,
    CITY_DISCOVERY_MODE,
    FESTIVAL_SEEDED_CITY_DISCOVERY_MODE,
    GOURMET_EXTERNAL_THEME_LABELS,
    NO_SUPPORT_THEME_LABELS,
    AttractionCandidate,
    CandidateThemeSplit,
    CitySelectContext,
    PrunedCityGroups,
    ensure_city_select_input,
    prepare_city_select_context,
    resolve_city_select_mode,
    split_candidate_themes,
    unique_theme_labels,
)
from lovv_agent_v2.models.schemas import SchemaValidationError

ATTRACTION_ENTITY_TYPE = "attraction"
DEFAULT_RETURN_DISTANCE = True
DEFAULT_RETURN_METADATA = True
_CHUNK_SUFFIX_PATTERN = re.compile(
    r"(?i)(?:::|#|/|_|-)?chunk(?:[-_:#/])?\d+$",
)
CITY_KEY_ALIASES = {
    "CITY#GOSEONG": "CITY#GOSEONG-GANGWON",
}


def allowed_city_pk(city_id: str) -> str:
    prefix, separator, suffix = city_id.partition("-")
    name = suffix if separator and len(prefix) == 2 and prefix.isupper() else city_id
    return f"CITY#{name.upper()}"


def prune_cities(
    candidates: Sequence[AttractionCandidate],
    searchable_place_themes: Sequence[str],
    *,
    allowed_city_ids: Sequence[str] | None = None,
) -> PrunedCityGroups:
    required_themes = tuple(
        theme
        for theme in normalize_string_sequence(
            searchable_place_themes,
            "searchable_place_themes",
        )
        if not is_excluded_place_search_theme(theme)
    )
    allowed = (
        {cid.strip().upper() for cid in normalize_string_sequence(allowed_city_ids, "allowed_city_ids")}
        if allowed_city_ids is not None
        else None
    )
    grouped: dict[str, list[AttractionCandidate]] = {}
    for candidate in candidates:
        city_key = candidate_city_key(candidate)
        if city_key is None:
            continue
        if allowed is not None:
            allowed_pks = {allowed_city_pk(cid) for cid in allowed}
            ddb_pk = (candidate.ddb_pk or "").upper()
            cand_city_id_upper = candidate.city_id.upper()
            if cand_city_id_upper not in allowed and ddb_pk not in allowed_pks:
                continue
        grouped.setdefault(city_key, []).append(candidate)

    survived: dict[str, tuple[AttractionCandidate, ...]] = {}
    available_themes_by_city: dict[str, tuple[str, ...]] = {}
    missing_themes_by_city: dict[str, tuple[str, ...]] = {}
    for city_id, city_candidates in grouped.items():
        city_themes = {
            theme
            for candidate in city_candidates
            for theme in candidate.theme_tags
        }
        available_themes_by_city[city_id] = tuple(
            theme for theme in required_themes if theme in city_themes
        )
        missing_themes_by_city[city_id] = tuple(
            theme for theme in required_themes if theme not in city_themes
        )
        survived[city_id] = tuple(city_candidates)

    return PrunedCityGroups(
        survived_groups=survived,
        eliminated_cities=(),
        available_themes_by_city=available_themes_by_city,
        missing_themes_by_city=missing_themes_by_city,
    )


def normalize_attraction_candidate(record: Mapping[str, Any]) -> AttractionCandidate:
    if not isinstance(record, Mapping):
        raise SchemaValidationError("attraction candidate record must be a mapping")
    key = required_text(first_present(record, "key", "id"), "key")
    metadata = metadata_from_record(record)
    entity_type = required_text(metadata.get("entity_type"), "metadata.entity_type")
    if entity_type != ATTRACTION_ENTITY_TYPE:
        raise SchemaValidationError("metadata.entity_type must be attraction")

    return AttractionCandidate(
        key=key,
        place_id=normalize_place_id(key=key, metadata=metadata),
        distance=numeric(first_present(record, "distance", "score"), "distance"),
        entity_type=entity_type,
        city_id=required_text(metadata.get("city_id"), "metadata.city_id"),
        city_name_ko=optional_text(metadata.get("city_name_ko"), "metadata.city_name_ko"),
        title=required_text(metadata.get("title"), "metadata.title"),
        theme_tags=normalize_string_sequence(metadata.get("theme_tags"), "metadata.theme_tags"),
        latitude=optional_numeric(metadata.get("latitude"), "metadata.latitude"),
        longitude=optional_numeric(metadata.get("longitude"), "metadata.longitude"),
        ddb_pk=optional_text(metadata.get("ddb_pk"), "metadata.ddb_pk"),
        ddb_sk=optional_text(metadata.get("ddb_sk"), "metadata.ddb_sk"),
        metadata=dict(metadata),
    )


def normalize_place_id(*, key: str, metadata: Mapping[str, Any]) -> str:
    metadata_place_id = optional_text(metadata.get("place_id"), "metadata.place_id")
    if metadata_place_id is not None:
        return metadata_place_id
    hash_parts = key.split("#")
    if len(hash_parts) >= 3 and hash_parts[-1].isdigit():
        return "#".join(hash_parts[:-1])
    normalized = _CHUNK_SUFFIX_PATTERN.sub("", key).strip()
    if not normalized:
        raise SchemaValidationError("place_id could not be normalized from key")
    return normalized


def candidate_city_key(candidate: AttractionCandidate) -> str | None:
    if candidate.ddb_pk:
        normalized = candidate.ddb_pk.strip().upper()
        return CITY_KEY_ALIASES.get(normalized, normalized)
    if candidate.city_id:
        return candidate.city_id.strip().upper()
    if candidate.city_name_ko:
        return candidate.city_name_ko.strip()
    return None


def normalize_query_vector(query_vector: Sequence[float]) -> list[float]:
    if isinstance(query_vector, (str, bytes)) or not isinstance(query_vector, Sequence):
        raise SchemaValidationError("query_vector must be a numeric sequence")
    if not query_vector:
        raise SchemaValidationError("query_vector must not be empty")
    return [numeric(value, "query_vector") for value in query_vector]


def resolve_place_search_theme(
    theme: str | None,
    theme_tags: Sequence[str] | None,
) -> str | None:
    merged: list[str] = []
    normalized_theme = optional_text(theme, "theme")
    if normalized_theme is not None:
        merged.append(normalized_theme)
    if theme_tags is not None:
        merged.extend(normalize_string_sequence(theme_tags, "theme_tags"))
    deduped = tuple(dict.fromkeys(merged))
    if len(deduped) > 1:
        raise SchemaValidationError(
            "search_candidates accepts one active theme per S3 Vector query",
        )
    return deduped[0] if deduped else None


def is_excluded_place_search_theme(theme: str) -> bool:
    return theme in NO_SUPPORT_THEME_LABELS


def metadata_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("metadata", {})
    if not isinstance(value, Mapping):
        raise SchemaValidationError("attraction candidate metadata must be a mapping")
    return dict(value)


def first_present(record: Mapping[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    joined = " or ".join(field_names)
    raise SchemaValidationError(f"missing required field: {joined}")


def normalize_string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(required_text(item, field_name) for item in value)


def required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field_name)


def numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def optional_numeric(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return numeric(value, field_name)


__all__ = [
    "ANCHORED_PLACE_SEARCH_MODE",
    "ATTRACTION_ENTITY_TYPE",
    "CITY_DISCOVERY_MODE",
    "DEFAULT_RETURN_DISTANCE",
    "DEFAULT_RETURN_METADATA",
    "FESTIVAL_SEEDED_CITY_DISCOVERY_MODE",
    "GOURMET_EXTERNAL_THEME_LABELS",
    "NO_SUPPORT_THEME_LABELS",
    "AttractionCandidate",
    "CandidateThemeSplit",
    "CitySelectContext",
    "PrunedCityGroups",
    "allowed_city_pk",
    "candidate_city_key",
    "ensure_city_select_input",
    "is_excluded_place_search_theme",
    "normalize_attraction_candidate",
    "normalize_query_vector",
    "normalize_string_sequence",
    "optional_text",
    "prepare_city_select_context",
    "prune_cities",
    "resolve_place_search_theme",
    "resolve_city_select_mode",
    "split_candidate_themes",
    "unique_theme_labels",
]
