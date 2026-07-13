from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


class ThemePlace(Protocol):
    place_id: str
    theme_tags: tuple[str, ...]
    is_seed: bool


TPlace = TypeVar("TPlace", bound=ThemePlace)
SortKey = Callable[[TPlace], tuple[bool, float, float, float]]
ThemeKey = Callable[[TPlace], str | None]


@dataclass(frozen=True, slots=True)
class ThemeSelectionInput(Generic[TPlace]):
    places: Sequence[TPlace]
    themes: tuple[str, ...]
    weights: Mapping[str, float] | None
    target_count: int
    sort_key: SortKey[TPlace]
    theme_key: ThemeKey[TPlace]


def select_by_theme_quota(selection_input: ThemeSelectionInput[TPlace]) -> tuple[TPlace, ...]:
    if not selection_input.themes:
        return tuple(sorted(selection_input.places, key=selection_input.sort_key, reverse=True))[
            : selection_input.target_count
        ]
    quotas = theme_quota(
        selection_input.themes,
        selection_input.weights,
        selection_input.target_count,
    )
    selected = _seed_places(selection_input)
    selected_ids = {place.place_id for place in selected}
    counts = Counter(selection_input.theme_key(place) for place in selected)
    ranked = tuple(sorted(selection_input.places, key=selection_input.sort_key, reverse=True))
    for theme in selection_input.themes:
        for place in ranked:
            if len(selected) >= selection_input.target_count or counts[theme] >= quotas[theme]:
                break
            if place.place_id not in selected_ids and selection_input.theme_key(place) == theme:
                selected.append(place)
                selected_ids.add(place.place_id)
                counts[theme] += 1
    for place in ranked:
        if len(selected) >= selection_input.target_count:
            break
        if place.place_id not in selected_ids and selection_input.theme_key(place) in selection_input.themes:
            selected.append(place)
            selected_ids.add(place.place_id)
    return tuple(selected)


def primary_theme(place: ThemePlace, themes: tuple[str, ...]) -> str | None:
    for theme in themes:
        if theme in place.theme_tags:
            return theme
    return place.theme_tags[0] if place.theme_tags else None


def selected_theme_counts(
    places: Sequence[TPlace],
    themes: tuple[str, ...],
    theme_key: ThemeKey[TPlace],
) -> dict[str, int]:
    counts = {theme: 0 for theme in themes}
    for place in places:
        theme = theme_key(place)
        if theme in counts:
            counts[theme] += 1
    return counts


def theme_quota(
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


def _seed_places(selection_input: ThemeSelectionInput[TPlace]) -> list[TPlace]:
    return [
        place
        for place in sorted(selection_input.places, key=selection_input.sort_key, reverse=True)
        if place.is_seed
    ]


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
