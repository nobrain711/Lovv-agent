from __future__ import annotations

from collections.abc import Mapping, Sequence

from lovv_agent_v2.tools.destination_policy import GOURMET_EXTERNAL_THEME_LABELS
from lovv_agent_v2.agents.city_select.scoring.service_validation import string_tuple


def scoreable_themes(active_themes: Sequence[str]) -> tuple[str, ...]:
    themes = string_tuple(active_themes, "active_themes")
    filtered: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        if theme in GOURMET_EXTERNAL_THEME_LABELS or theme in seen:
            continue
        seen.add(theme)
        filtered.append(theme)
    return tuple(filtered)


def equal_weights(themes: Sequence[str]) -> dict[str, float]:
    if not themes:
        return {}
    return {theme: 1.0 / len(themes) for theme in themes}


def normalized_theme_weights(
    themes: tuple[str, ...],
    theme_weights: Mapping[str, float] | None,
) -> dict[str, float]:
    if not themes:
        return {}
    if not theme_weights:
        return equal_weights(themes)
    weights = {theme: theme_weights.get(theme, 0.0) for theme in themes}
    total_weight = sum(weights.values())
    if total_weight <= 0.0:
        return equal_weights(themes)
    return {theme: weight / total_weight for theme, weight in weights.items()}


def theme_score_with_weights(
    best_similarity_by_theme: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    return sum(
        weights.get(theme, 0.0) * best_similarity
        if best_similarity > 0.0
        else -weights.get(theme, 0.0)
        for theme, best_similarity in best_similarity_by_theme.items()
    )


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)
