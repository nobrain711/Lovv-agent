from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.tools.destination_policy import ATTRACTION_ENTITY_TYPE
from lovv_agent_v2.agents.city_select.scoring.service_candidates import (
    coerce_scored_place,
    similarity_from_distance,
    zero_city_breakdown,
    zero_place_components,
)
from lovv_agent_v2.agents.city_select.scoring.service_geo import (
    city_distance_penalty,
    haversine_distance,
)
from lovv_agent_v2.agents.city_select.scoring.service_theme import (
    clamp,
    equal_weights,
    normalized_theme_weights,
    scoreable_themes,
    theme_score_with_weights,
)
from lovv_agent_v2.agents.city_select.scoring.service_types import (
    CityScoreResult,
    PlaceScoreResult,
    ScoreBreakdown,
)
from lovv_agent_v2.agents.city_select.scoring.service_validation import (
    candidate_value,
    numeric,
    optional_float,
    optional_text,
    place_id,
    positive_int,
    required_text,
    round4,
    string_tuple,
)
from lovv_agent_v2.models.profile import PROFILE_SCORE_CAP

TOOL_NAME = "ScoringTool"

RESPONSIBILITY = "Compute deterministic place and city score breakdowns."

CANDIDATE_SUFFICIENCY_THRESHOLD = 5


@dataclass(frozen=True, slots=True)
class ScoringTool:
    def score_place(
        self,
        candidate: Any,
        active_themes: Sequence[str],
        *,
        reference_location: Any | None = None,
    ) -> PlaceScoreResult:
        return score_place(
            candidate,
            active_themes,
            reference_location=reference_location,
        )

    def score_city(
        self,
        *,
        city_id: str,
        places: Sequence[Any],
        active_themes: Sequence[str],
        user_location: Any | None = None,
        primary_budget: int = CANDIDATE_SUFFICIENCY_THRESHOLD,
        congestion_index: float = 0.0,
        w_cong: float = 0.0,
        theme_weights: Mapping[str, float] | None = None,
        trip_type: str | None = None,
    ) -> CityScoreResult:
        return score_city(
            city_id=city_id,
            places=places,
            active_themes=active_themes,
            user_location=user_location,
            primary_budget=primary_budget,
            congestion_index=congestion_index,
            w_cong=w_cong,
            theme_weights=theme_weights,
            trip_type=trip_type,
        )


def score_place(
    candidate: Any,
    active_themes: Sequence[str],
    *,
    reference_location: Any | None = None,
) -> PlaceScoreResult:
    del active_themes, reference_location
    entity_type = optional_text(candidate_value(candidate, "entity_type", "entityType"))
    normalized_place_id = place_id(candidate)
    title = optional_text(candidate_value(candidate, "title", "name"))
    city_id = optional_text(candidate_value(candidate, "city_id", "cityId"))
    theme_tags = string_tuple(
        candidate_value(candidate, "theme_tags", "themeTags"),
        "theme_tags",
    )
    latitude = optional_float(candidate_value(candidate, "latitude", "lat"))
    longitude = optional_float(candidate_value(candidate, "longitude", "lng", "lon"))

    if entity_type != ATTRACTION_ENTITY_TYPE:
        return PlaceScoreResult(
            place=candidate,
            place_id=normalized_place_id,
            title=title,
            city_id=city_id,
            theme_tags=theme_tags,
            latitude=latitude,
            longitude=longitude,
            score_components=zero_place_components(),
            scored=False,
            exclusion_reason=f"unsupported_entity_type:{entity_type or 'missing'}",
        )

    raw_similarity = similarity_from_distance(candidate_value(candidate, "distance"))
    return PlaceScoreResult(
        place=candidate,
        place_id=normalized_place_id,
        title=title,
        city_id=city_id,
        theme_tags=theme_tags,
        latitude=latitude,
        longitude=longitude,
        score_components={
            "raw_similarity": round4(raw_similarity),
        },
    )


def score_city(
    *,
    city_id: str,
    places: Sequence[Any],
    active_themes: Sequence[str],
    user_location: Any | None = None,
    primary_budget: int = CANDIDATE_SUFFICIENCY_THRESHOLD,
    congestion_index: float = 0.0,
    w_cong: float = 0.0,
    theme_weights: Mapping[str, float] | None = None,
    trip_type: str | None = None,
) -> CityScoreResult:
    normalized_city_id = required_text(city_id, "city_id")
    budget = positive_int(primary_budget, "primary_budget")
    scored_places = tuple(
        place for place in (coerce_scored_place(item) for item in places) if place.scored
    )
    if not scored_places:
        return CityScoreResult(
            city_id=normalized_city_id,
            city_score=0.0,
            breakdown=zero_city_breakdown(),
            top_place_ids=(),
            candidate_count=0,
        )

    top_places = tuple(
        sorted(
            scored_places,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
            reverse=True,
        )[:budget],
    )
    active_scoreable_themes = scoreable_themes(active_themes)
    weights = normalized_theme_weights(active_scoreable_themes, theme_weights)
    best_similarity_by_theme = {
        theme: max(
            (
                place.score_components.get("raw_similarity", 0.0)
                for place in scored_places
                if theme in place.theme_tags
            ),
            default=0.0,
        )
        for theme in active_scoreable_themes
    }
    weighted_theme_coverage = sum(
        weights.get(theme, 0.0) * best_similarity
        for theme, best_similarity in best_similarity_by_theme.items()
        if best_similarity > 0.0
    )
    weighted_missing_theme_penalty = sum(
        weights.get(theme, 0.0)
        for theme, best_similarity in best_similarity_by_theme.items()
        if best_similarity <= 0.0
    )
    weighted_theme_score = weighted_theme_coverage - weighted_missing_theme_penalty
    equal_theme_score = theme_score_with_weights(
        best_similarity_by_theme,
        equal_weights(active_scoreable_themes),
    )
    capped_theme_score = (
        weighted_theme_score
        if not theme_weights
        else equal_theme_score
        + clamp(
            weighted_theme_score - equal_theme_score,
            -PROFILE_SCORE_CAP,
            PROFILE_SCORE_CAP,
        )
    )
    distance_penalty = city_distance_penalty(scored_places, user_location, trip_type)
    congestion_penalty = numeric(congestion_index, "congestion_index") * numeric(
        w_cong,
        "w_cong",
    )
    city_score = capped_theme_score - distance_penalty - congestion_penalty
    return CityScoreResult(
        city_id=normalized_city_id,
        city_score=round4(city_score),
        breakdown=ScoreBreakdown(
            weighted_theme_coverage=round4(weighted_theme_coverage),
            weighted_missing_theme_penalty=round4(weighted_missing_theme_penalty),
            distance_penalty=round4(distance_penalty),
            congestion_penalty=round4(congestion_penalty),
        ),
        top_place_ids=tuple(place.place_id for place in top_places),
        candidate_count=len(scored_places),
    )

__all__ = [
    "CANDIDATE_SUFFICIENCY_THRESHOLD",
    "CityScoreResult",
    "PlaceScoreResult",
    "RESPONSIBILITY",
    "ScoreBreakdown",
    "ScoringTool",
    "TOOL_NAME",
    "haversine_distance",
    "score_city",
    "score_place",
]
