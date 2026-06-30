from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from lovv_agent_v2.models.schemas import SchemaValidationError

THEME_ID_TO_LABEL: Final[dict[str, str]] = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
}

PROFILE_ACTIVATION_SAVED_TRIP_COUNT: Final = 3
PROFILE_ALPHA: Final = 1.5
PROFILE_MIN_WEIGHT: Final = 0.8
PROFILE_MAX_WEIGHT: Final = 1.3
PROFILE_SCORE_CAP: Final = 0.05


@dataclass(frozen=True, slots=True)
class LovvUserProfile:
    saved_trip_count: int
    saved_theme_counts: Mapping[str, int]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LovvUserProfile":
        saved_trip_count = payload.get("saved_trip_count", 0)
        if isinstance(saved_trip_count, bool) or not isinstance(saved_trip_count, int):
            raise SchemaValidationError("saved_trip_count must be an integer")
        counts = payload.get("saved_theme_counts", {})
        if not isinstance(counts, Mapping):
            raise SchemaValidationError("saved_theme_counts must be an object")
        return cls(
            saved_trip_count=saved_trip_count,
            saved_theme_counts=_theme_counts(counts),
        )


@dataclass(frozen=True, slots=True)
class ProfileThemeWeights:
    active: bool
    theme_weights: dict[str, float]
    theme_id_weights: dict[str, float]

    def to_audit(self) -> dict[str, Any]:
        return {
            "profile_active": self.active,
            "theme_weights": dict(self.theme_weights),
            "theme_id_weights": dict(self.theme_id_weights),
            "activation_saved_trip_count": PROFILE_ACTIVATION_SAVED_TRIP_COUNT,
            "alpha": PROFILE_ALPHA,
            "weight_range": {
                "id": "medium",
                "min": PROFILE_MIN_WEIGHT,
                "max": PROFILE_MAX_WEIGHT,
            },
            "profile_score_cap": PROFILE_SCORE_CAP,
        }


def build_profile_theme_weights(
    profile: LovvUserProfile | None,
    active_required_themes: Sequence[str],
) -> ProfileThemeWeights:
    if profile is None or profile.saved_trip_count < PROFILE_ACTIVATION_SAVED_TRIP_COUNT:
        return ProfileThemeWeights(active=False, theme_weights={}, theme_id_weights={})
    total = sum(profile.saved_theme_counts.values())
    confidence = min(profile.saved_trip_count / PROFILE_ACTIVATION_SAVED_TRIP_COUNT, 1.0)
    theme_id_weights = {
        theme_id: _effective_weight(
            profile.saved_theme_counts.get(theme_id, 0),
            total,
            confidence,
        )
        for theme_id in THEME_ID_TO_LABEL
    }
    active_set = set(active_required_themes)
    theme_weights = {
        label: theme_id_weights[theme_id]
        for theme_id, label in THEME_ID_TO_LABEL.items()
        if label in active_set
    }
    return ProfileThemeWeights(
        active=True,
        theme_weights=theme_weights,
        theme_id_weights=theme_id_weights,
    )


def _theme_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for theme_id in THEME_ID_TO_LABEL:
        value = payload.get(theme_id, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaValidationError(f"saved_theme_counts.{theme_id} must be an integer")
        counts[theme_id] = value
    return counts


def _effective_weight(count: int, total: int, confidence: float) -> float:
    observed_ratio = count / total if total > 0 else 0.2
    raw_weight = 1.0 + PROFILE_ALPHA * (observed_ratio - 0.2)
    learned_weight = min(max(raw_weight, PROFILE_MIN_WEIGHT), PROFILE_MAX_WEIGHT)
    return round(1.0 + confidence * (learned_weight - 1.0), 6)


__all__ = [
    "LovvUserProfile",
    "ProfileThemeWeights",
    "THEME_ID_TO_LABEL",
    "build_profile_theme_weights",
]
