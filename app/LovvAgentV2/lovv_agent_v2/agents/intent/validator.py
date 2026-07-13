from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreferenceValidationResult:
    contradiction_reasons: tuple[str, ...] = ()

    @property
    def needs_clarification(self) -> bool:
        return bool(self.contradiction_reasons)


def validate_preference_sets(
    *,
    preferred_theme_ids: Sequence[str],
    disliked_theme_ids: Sequence[str],
    preferred_region_ids: Sequence[str],
    disliked_region_ids: Sequence[str],
) -> PreferenceValidationResult:
    theme_overlap = _ordered_overlap(preferred_theme_ids, disliked_theme_ids)
    region_overlap = _ordered_overlap(preferred_region_ids, disliked_region_ids)
    reasons = tuple(f"theme:{theme_id}" for theme_id in theme_overlap) + tuple(
        f"region:{region_id}" for region_id in region_overlap
    )
    return PreferenceValidationResult(contradiction_reasons=reasons)


def _ordered_overlap(
    preferred_ids: Sequence[str],
    disliked_ids: Sequence[str],
) -> tuple[str, ...]:
    disliked_set = set(disliked_ids)
    return tuple(item_id for item_id in _dedupe(preferred_ids) if item_id in disliked_set)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
