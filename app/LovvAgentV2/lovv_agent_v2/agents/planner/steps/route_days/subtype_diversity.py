from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


class SubtypedPlace(Protocol):
    place_id: str
    is_seed: bool
    payload: Mapping[str, object]


TPlace = TypeVar("TPlace", bound=SubtypedPlace)
SortKey = Callable[[TPlace], tuple[bool, float, float, float]]
ThemeKey = Callable[[TPlace], str | None]

SUBTYPE_FIELDS = (
    "attraction_subtype_code",
)


@dataclass(frozen=True, slots=True)
class SubtypeCapResult(Generic[TPlace]):
    places: tuple[TPlace, ...]
    limit: int
    limits: dict[str, int]
    relaxed: bool


@dataclass(frozen=True, slots=True)
class SubtypeCapInput(Generic[TPlace]):
    selected: Sequence[TPlace]
    pool: Sequence[TPlace]
    themes: tuple[str, ...]
    quotas: Mapping[str, int]
    target_count: int
    min_count: int
    sort_key: SortKey[TPlace]
    theme_key: ThemeKey[TPlace]


def apply_theme_subtype_cap(cap_input: SubtypeCapInput[TPlace]) -> SubtypeCapResult[TPlace]:
    if not cap_input.themes:
        return SubtypeCapResult(places=tuple(cap_input.selected), limit=0, limits={}, relaxed=False)
    limits = _limits_by_theme(cap_input)
    chosen = _seed_places(cap_input.selected, cap_input.sort_key)
    chosen_ids = {place.place_id for place in chosen}
    theme_counts = Counter(cap_input.theme_key(place) for place in chosen)
    subtype_counts_by_key = Counter(
        (cap_input.theme_key(place), _subtype_key(place)) for place in chosen
    )
    ranked = tuple(sorted(cap_input.pool, key=cap_input.sort_key, reverse=True))
    for theme in cap_input.themes:
        for place in ranked:
            if len(chosen) >= cap_input.target_count or theme_counts[theme] >= cap_input.quotas[theme]:
                break
            subtype = _subtype_key(place)
            capped = subtype and subtype_counts_by_key[(theme, subtype)] >= limits[theme]
            if place.place_id not in chosen_ids and cap_input.theme_key(place) == theme and not capped:
                chosen.append(place)
                chosen_ids.add(place.place_id)
                theme_counts[theme] += 1
                subtype_counts_by_key[(theme, subtype)] += 1
    relaxed = False
    if len(chosen) < cap_input.min_count:
        relaxed = True
        for place in ranked:
            if len(chosen) >= cap_input.min_count:
                break
            if place.place_id not in chosen_ids and cap_input.theme_key(place) in cap_input.themes:
                chosen.append(place)
                chosen_ids.add(place.place_id)
    return SubtypeCapResult(
        places=tuple(chosen[: cap_input.target_count]),
        limit=max(limits.values(), default=0),
        limits=limits,
        relaxed=relaxed,
    )


def subtype_counts(places: Sequence[SubtypedPlace]) -> dict[str, int]:
    counts = Counter(_subtype_key(place) for place in places)
    counts.pop("", None)
    return dict(counts)


def _seed_places(places: Sequence[TPlace], sort_key: SortKey[TPlace]) -> list[TPlace]:
    return [place for place in sorted(places, key=sort_key, reverse=True) if place.is_seed]


def _limits_by_theme(cap_input: SubtypeCapInput[TPlace]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for theme in cap_input.themes:
        quota = max(cap_input.quotas.get(theme, 0), 1)
        subtypes = {
            _subtype_key(place)
            for place in cap_input.pool
            if cap_input.theme_key(place) == theme and _subtype_key(place)
        }
        limits[theme] = quota if len(subtypes) <= 1 else math.ceil(quota / min(len(subtypes), 3))
    return limits


def _subtype_key(place: SubtypedPlace) -> str:
    for field_name in SUBTYPE_FIELDS:
        value = place.payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
