from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from lovv_agent_v2.models.schemas import SchemaValidationError

RAW_SIMILARITY_BLEND_WEIGHT: Final = 0.7
SOFT_SIMILARITY_BLEND_WEIGHT: Final = 0.3


@dataclass(frozen=True, slots=True)
class PlannerPlace:
    place_id: str
    title: str
    theme_tags: tuple[str, ...]
    similarity: float
    soft_similarity: float
    latitude: float | None
    longitude: float | None
    payload: dict[str, object]
    assigned_theme: str | None = None
    is_seed: bool = False


def coerce_place(payload: Mapping[str, object]) -> PlannerPlace:
    score_components = _mapping(_mapping(payload.get("score_audit")).get("score_components"))
    similarity = _float(score_components.get("raw_similarity", payload.get("sim", 0.0)))
    return PlannerPlace(
        place_id=text(payload.get("place_id", payload.get("placeId")), "place_id"),
        title=text(payload.get("title"), "title"),
        theme_tags=theme_tuple(payload.get("theme_tags", payload.get("themeTags", ()))),
        similarity=similarity,
        soft_similarity=_float(payload.get("soft_similarity", payload.get("soft_sim", similarity))),
        latitude=_optional_float(payload.get("latitude", payload.get("lat"))),
        longitude=_optional_float(payload.get("longitude", payload.get("lon"))),
        payload=dict(payload),
        assigned_theme=_optional_text(payload.get("assigned_theme")),
    )


def with_seed_flag(place: PlannerPlace, selected_seed_ids: set[str]) -> PlannerPlace:
    return replace(place, is_seed=place.place_id in selected_seed_ids)


def with_semantic_seed_source(place: PlannerPlace, seed_source: str) -> PlannerPlace:
    payload = dict(place.payload)
    payload["seed_source"] = seed_source
    return replace(place, is_seed=True, payload=payload)


def with_soft_channel(place: PlannerPlace, soft_place: PlannerPlace) -> PlannerPlace:
    blended_similarity = round(
        (place.similarity * RAW_SIMILARITY_BLEND_WEIGHT)
        + (soft_place.soft_similarity * SOFT_SIMILARITY_BLEND_WEIGHT),
        4,
    )
    payload = dict(place.payload)
    score_audit = dict(_mapping(payload.get("score_audit")))
    score_components = dict(_mapping(score_audit.get("score_components")))
    score_components["raw_similarity"] = place.similarity
    score_components["soft_similarity"] = soft_place.soft_similarity
    score_components["raw_soft_blended_similarity"] = blended_similarity
    score_audit["score_components"] = score_components
    payload["score_audit"] = score_audit
    payload["soft_similarity"] = soft_place.soft_similarity
    payload["raw_soft_blended_similarity"] = blended_similarity
    payload["retrieval_channels"] = ("raw", "soft")
    return replace(place, soft_similarity=soft_place.soft_similarity, payload=payload)


def merge_by_place_id(places: Sequence[PlannerPlace]) -> tuple[PlannerPlace, ...]:
    merged: dict[str, PlannerPlace] = {}
    for place in sorted(places, key=selection_sort_key, reverse=True):
        merged.setdefault(place.place_id, place)
    return tuple(merged.values())


def selection_sort_key(place: PlannerPlace) -> tuple[bool, float, float, float]:
    return (place.is_seed, _ranking_similarity(place), place.soft_similarity, place.similarity)


def seed_ids(seeds: Sequence[Mapping[str, object]]) -> set[str]:
    return {text(seed.get("place_id", seed.get("placeId")), "seed.place_id") for seed in seeds}


def theme_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (text(value, "theme"),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text(item, "theme") for item in value)


def positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or value <= 0:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


def text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _ranking_similarity(place: PlannerPlace) -> float:
    ranking_similarity = _float(place.payload.get("raw_soft_blended_similarity"))
    if ranking_similarity > 0:
        return ranking_similarity
    return place.soft_similarity


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
