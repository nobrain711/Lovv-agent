from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service_types import (
    PlaceScoreResult,
    ScoreBreakdown,
)
from lovv_agent_v2.agents.city_select.scoring.service_validation import (
    candidate_value,
    mapping_get,
    optional_float,
    optional_text,
    place_id,
    required_text,
    round4,
    string_tuple,
)


def coerce_scored_place(place: Any) -> PlaceScoreResult:
    if isinstance(place, PlaceScoreResult):
        return place
    if isinstance(place, Mapping):
        score_components = dict(mapping_get(place, "score_components", default={}))
        if "raw_similarity" not in score_components:
            score_components["raw_similarity"] = similarity_from_distance(
                mapping_get(place, "distance", default=None),
            )
        return PlaceScoreResult(
            place=place,
            place_id=required_text(mapping_get(place, "place_id", "placeId"), "place_id"),
            title=optional_text(mapping_get(place, "title", "name", default=None)),
            city_id=optional_text(mapping_get(place, "city_id", "cityId", default=None)),
            theme_tags=string_tuple(
                mapping_get(place, "theme_tags", "themeTags", default=()),
                "theme_tags",
            ),
            latitude=optional_float(mapping_get(place, "latitude", "lat", default=None)),
            longitude=optional_float(
                mapping_get(place, "longitude", "lng", "lon", default=None),
            ),
            score_components=score_components,
            scored=bool(mapping_get(place, "scored", default=True)),
            exclusion_reason=optional_text(
                mapping_get(place, "exclusion_reason", default=None),
            ),
        )
    return PlaceScoreResult(
        place=place,
        place_id=place_id(place),
        title=optional_text(candidate_value(place, "title", "name")),
        city_id=optional_text(candidate_value(place, "city_id", "cityId")),
        theme_tags=string_tuple(
            candidate_value(place, "theme_tags", "themeTags"),
            "theme_tags",
        ),
        latitude=optional_float(candidate_value(place, "latitude", "lat")),
        longitude=optional_float(candidate_value(place, "longitude", "lng", "lon")),
        score_components={
            "raw_similarity": round4(
                similarity_from_distance(candidate_value(place, "distance")),
            ),
        },
    )


def similarity_from_distance(value: Any) -> float:
    distance = optional_float(value)
    if distance is None:
        return 0.0
    return max(1.0 - distance, 0.0)


def zero_place_components() -> dict[str, float]:
    return {
        "raw_similarity": 0.0,
    }


def zero_city_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        weighted_theme_coverage=0.0,
        weighted_missing_theme_penalty=0.0,
        distance_penalty=0.0,
        congestion_penalty=0.0,
    )
