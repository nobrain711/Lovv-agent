from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlaceScoreResult:
    place: Any
    place_id: str
    title: str | None
    city_id: str | None
    theme_tags: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    score_components: dict[str, float]
    scored: bool = True
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    weighted_theme_coverage: float
    weighted_missing_theme_penalty: float
    distance_penalty: float
    congestion_penalty: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CityScoreResult:
    city_id: str
    city_score: float
    breakdown: ScoreBreakdown
    top_place_ids: tuple[str, ...]
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "city_id": self.city_id,
            "city_score": self.city_score,
            "score_breakdown": self.breakdown.to_dict(),
            "top_place_ids": list(self.top_place_ids),
            "candidate_count": self.candidate_count,
        }
