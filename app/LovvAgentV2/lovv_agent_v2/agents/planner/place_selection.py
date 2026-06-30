from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from lovv_agent_v2.models.schemas import SchemaValidationError

DEFAULT_RELEVANCE_RATIO = 0.6
TRIP_RELEVANCE_RATIOS: Mapping[str, float] = {
    "daytrip": 0.7,
    "2d1n": 0.6,
    "3d2n": 0.5,
}


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


@dataclass(frozen=True, slots=True)
class PlannerSelectionInput:
    raw_places: Sequence[Mapping[str, object]]
    soft_places: Sequence[Mapping[str, object]]
    seeds: Sequence[Mapping[str, object]]
    active_themes: Sequence[str]
    theme_weights: Mapping[str, float] | None
    trip_type: str
    target_count: int


@dataclass(frozen=True, slots=True)
class PlannerSelectionResult:
    places: tuple[PlannerPlace, ...]
    reserve: tuple[PlannerPlace, ...]
    audit: dict[str, object]


def build_working_set(selection_input: PlannerSelectionInput) -> PlannerSelectionResult:
    raw_places = tuple(_coerce_place(place) for place in selection_input.raw_places)
    soft_places = tuple(_coerce_place(place) for place in selection_input.soft_places)
    seed_ids = _seed_ids(selection_input.seeds)
    themes = _theme_tuple(selection_input.active_themes)
    target_count = _positive_int(selection_input.target_count, "target_count")
    ratio = TRIP_RELEVANCE_RATIOS.get(selection_input.trip_type, DEFAULT_RELEVANCE_RATIO)

    best_raw = max((place.similarity for place in raw_places), default=0.0)
    raw_threshold = round(best_raw * ratio, 4)
    raw_kept = tuple(
        _with_seed_flag(place, seed_ids)
        for place in raw_places
        if place.similarity >= raw_threshold or place.place_id in seed_ids
    )
    raw_ids = {place.place_id for place in raw_kept}

    best_soft = max((place.soft_similarity for place in soft_places), default=0.0)
    soft_threshold = round(best_soft * DEFAULT_RELEVANCE_RATIO, 4)
    soft_candidates = tuple(
        _with_seed_flag(place, seed_ids)
        for place in soft_places
        if place.place_id not in raw_ids and place.soft_similarity >= soft_threshold
    )
    soft_on_theme = tuple(
        place for place in soft_candidates if _matches_any_theme(place, themes)
    )
    soft_off_theme_count = len(soft_candidates) - len(soft_on_theme)
    merged = _merge_by_place_id((*raw_kept, *soft_on_theme))
    selected = _apply_theme_quota(
        merged,
        themes=themes,
        weights=selection_input.theme_weights,
        target_count=target_count,
    )
    selected_ids = {place.place_id for place in selected}
    reserve = tuple(place for place in merged if place.place_id not in selected_ids)
    audit: dict[str, object] = {
        "relevance_ratio": ratio,
        "relative_threshold": raw_threshold,
        "raw_kept_count": len(raw_kept),
        "seed_preserved_count": sum(
            1 for place in selected if place.is_seed and place.similarity < raw_threshold
        ),
        "soft_threshold": soft_threshold,
        "soft_on_theme_added_count": len(soft_on_theme),
        "soft_off_theme_excluded_count": soft_off_theme_count,
        "theme_quota": _theme_quota(themes, selection_input.theme_weights, target_count),
        "theme_counts": _selected_theme_counts(selected, themes),
        "subtype_counts": _payload_value_counts(selected, "subtype"),
        "availability_policy": "unknown_availability_kept_with_audit",
        "profile_cap_policy": "profile_cap_not_applied_without_profile_payload",
    }
    return PlannerSelectionResult(places=selected, reserve=reserve, audit=audit)


def _apply_theme_quota(
    places: Sequence[PlannerPlace],
    *,
    themes: tuple[str, ...],
    weights: Mapping[str, float] | None,
    target_count: int,
) -> tuple[PlannerPlace, ...]:
    if not themes:
        return tuple(sorted(places, key=_selection_sort_key, reverse=True))[:target_count]
    quotas = _theme_quota(themes, weights, target_count)
    selected: list[PlannerPlace] = []
    selected_ids: set[str] = set()
    for place in sorted(places, key=_selection_sort_key, reverse=True):
        if place.is_seed:
            selected.append(place)
            selected_ids.add(place.place_id)
    theme_counts = Counter(_primary_theme(place, themes) for place in selected)
    for theme in themes:
        matching = [
            place
            for place in sorted(places, key=_selection_sort_key, reverse=True)
            if place.place_id not in selected_ids and theme in place.theme_tags
        ]
        for place in matching:
            if theme_counts[theme] >= quotas[theme] or len(selected) >= target_count:
                break
            selected.append(place)
            selected_ids.add(place.place_id)
            theme_counts[theme] += 1
    for place in sorted(places, key=_selection_sort_key, reverse=True):
        if len(selected) >= target_count:
            break
        if place.place_id not in selected_ids:
            selected.append(place)
            selected_ids.add(place.place_id)
    return tuple(selected)


def _theme_quota(
    themes: tuple[str, ...],
    weights: Mapping[str, float] | None,
    target_count: int,
) -> dict[str, int]:
    if not themes:
        return {}
    normalized = _normalized_weights(themes, weights)
    floors = {theme: math.floor(target_count * normalized[theme]) for theme in themes}
    remainder = target_count - sum(floors.values())
    ranked = sorted(
        themes,
        key=lambda theme: (target_count * normalized[theme] - floors[theme], normalized[theme]),
        reverse=True,
    )
    for theme in ranked[:remainder]:
        floors[theme] += 1
    return floors


def _normalized_weights(
    themes: tuple[str, ...],
    weights: Mapping[str, float] | None,
) -> dict[str, float]:
    if weights is None:
        return {theme: 1.0 / len(themes) for theme in themes}
    raw = {theme: max(float(weights.get(theme, 0.0)), 0.0) for theme in themes}
    total = sum(raw.values())
    if total <= 0.0:
        return {theme: 1.0 / len(themes) for theme in themes}
    return {theme: value / total for theme, value in raw.items()}


def _coerce_place(payload: Mapping[str, object]) -> PlannerPlace:
    score_components = _mapping(_mapping(payload.get("score_audit")).get("score_components"))
    similarity = _float(score_components.get("raw_similarity", payload.get("sim", 0.0)))
    return PlannerPlace(
        place_id=_text(payload.get("place_id", payload.get("placeId")), "place_id"),
        title=_text(payload.get("title"), "title"),
        theme_tags=_theme_tuple(payload.get("theme_tags", payload.get("themeTags", ()))),
        similarity=similarity,
        soft_similarity=_float(payload.get("soft_similarity", payload.get("soft_sim", similarity))),
        latitude=_optional_float(payload.get("latitude", payload.get("lat"))),
        longitude=_optional_float(payload.get("longitude", payload.get("lon"))),
        payload=dict(payload),
        assigned_theme=_optional_text(payload.get("assigned_theme")),
    )


def _with_seed_flag(place: PlannerPlace, seed_ids: set[str]) -> PlannerPlace:
    return replace(place, is_seed=place.place_id in seed_ids)


def _merge_by_place_id(places: Sequence[PlannerPlace]) -> tuple[PlannerPlace, ...]:
    merged: dict[str, PlannerPlace] = {}
    for place in sorted(places, key=_selection_sort_key, reverse=True):
        merged.setdefault(place.place_id, place)
    return tuple(merged.values())


def _selection_sort_key(place: PlannerPlace) -> tuple[bool, float, float]:
    return (place.is_seed, place.soft_similarity, place.similarity)


def _matches_any_theme(place: PlannerPlace, themes: tuple[str, ...]) -> bool:
    return bool(set(place.theme_tags).intersection(themes))


def _primary_theme(place: PlannerPlace, themes: tuple[str, ...]) -> str | None:
    for theme in themes:
        if theme in place.theme_tags:
            return theme
    return place.theme_tags[0] if place.theme_tags else None


def _selected_theme_counts(
    places: Sequence[PlannerPlace],
    themes: tuple[str, ...],
) -> dict[str, int]:
    counts = {theme: 0 for theme in themes}
    for place in places:
        theme = _primary_theme(place, themes)
        if theme in counts:
            counts[theme] += 1
    return counts


def _payload_value_counts(places: Sequence[PlannerPlace], field_name: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for place in places:
        value = place.payload.get(field_name)
        if isinstance(value, str) and value.strip():
            counts[value.strip()] += 1
    return dict(counts)


def _seed_ids(seeds: Sequence[Mapping[str, object]]) -> set[str]:
    return {_text(seed.get("place_id", seed.get("placeId")), "seed.place_id") for seed in seeds}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _theme_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_text(value, "theme"),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_text(item, "theme") for item in value)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


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


def _positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or value <= 0:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value
