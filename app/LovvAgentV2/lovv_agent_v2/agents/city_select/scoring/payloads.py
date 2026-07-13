from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult
from lovv_agent_v2.tools.city_select_contracts import CitySelectContext
from lovv_agent_v2.agents.city_select.scoring.ranking import _candidate_attr, _city_name_from_group


def _ddb_pk_from_group(city_id: str, scored_places: Sequence[PlaceScoreResult]) -> str:
    for place in scored_places:
        ddb_pk = _candidate_attr(place.place, "ddb_pk")
        if ddb_pk is not None:
            return str(ddb_pk).strip().upper()
    return city_id.strip().upper()


def _representative_seed_payload(place: PlaceScoreResult) -> dict[str, Any]:
    theme = place.theme_tags[0] if place.theme_tags else None
    return {
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "theme": theme,
        "sim": place.score_components.get("raw_similarity", 0.0),
        "lat": place.latitude,
        "lon": place.longitude,
        "attraction_subtype_code": _candidate_attr(place.place, "attraction_subtype_code"),
    }


def _seed_payload(place: PlaceScoreResult, theme: str) -> dict[str, Any]:
    raw_similarity = place.score_components.get("raw_similarity", 0.0)
    return {
        "theme": theme,
        "theme_tags": (theme,),
        "assigned_theme": theme,
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "sim": raw_similarity,
        "soft_similarity": raw_similarity,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "city_id": place.city_id,
        "score_audit": {"score_components": {"raw_similarity": raw_similarity}},
        "attraction_subtype_code": _candidate_attr(place.place, "attraction_subtype_code"),
        "must_include": True,
    }


def _seed_payloads(
    scored_places: Sequence[PlaceScoreResult],
    themes: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    seeds: list[dict[str, Any]] = []
    for theme in themes:
        matching = [place for place in scored_places if theme in place.theme_tags]
        if not matching:
            continue
        best = max(
            matching,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
        )
        seeds.append(_seed_payload(best, theme))
    return tuple(seeds)


def _headline_seed(seeds: Sequence[Mapping[str, Any]]) -> str | None:
    if not seeds:
        return None
    seed = max(seeds, key=lambda item: float(item.get("sim", 0.0)))
    place_id = seed.get("place_id")
    return place_id if isinstance(place_id, str) else None


def _theme_evidence_payload(
    scored_places: Sequence[PlaceScoreResult],
    themes: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    evidence: list[dict[str, Any]] = []
    for theme in themes:
        matching = [place for place in scored_places if theme in place.theme_tags]
        if not matching:
            continue
        best = max(
            matching,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
        )
        similarity = best.score_components.get("raw_similarity", 0.0)
        evidence.append(
            {
                "theme": theme,
                "best_place": {
                    "place_id": best.place_id,
                    "title": best.title,
                    "sim": similarity,
                },
                "coverage_strength": similarity,
            },
        )
    return tuple(evidence)


def _alternative_city_payload(
    city_rankings: Sequence[Mapping[str, Any]],
    scored_groups: Mapping[str, Sequence[PlaceScoreResult]],
    *,
    selected_city_id: str,
    themes: Sequence[str],
) -> dict[str, Any] | None:
    if len(city_rankings) < 2:
        return None
    selected_score = float(city_rankings[0]["city_score"])
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        if city_id == selected_city_id:
            continue
        scored_places = scored_groups[city_id]
        return {
            "city_id": city_id,
            "ddb_pk": _ddb_pk_from_group(city_id, scored_places),
            "city_name_ko": ranking.get("city_name_ko"),
            "score_delta": round(selected_score - float(ranking["city_score"]), 4),
            "seeds": list(_seed_payloads(scored_places, themes)),
        }
    return None


def _passthrough_payload(context: CitySelectContext) -> dict[str, Any]:
    location = context.candidate_input.user_location
    user_location = None
    if location is not None:
        user_location = {
            "latitude": location.latitude,
            "longitude": location.longitude,
        }
    return {
        "active_themes": list(context.theme_split.active_required_themes),
        "theme_weights": dict(context.candidate_input.theme_weights or {}),
        "trip_duration": context.candidate_input.trip_type,
        "congestion_pref": context.candidate_input.congestion_pref,
        "transport_pref": context.candidate_input.transport_pref,
        "soft_query": context.candidate_input.soft_preference_query,
        "user_location": user_location,
        "session_avoid": [],
    }


def _selection_reason_codes(
    *,
    context: CitySelectContext,
    score_breakdown: Mapping[str, float],
    alternative_city: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    codes: list[str] = []
    if context.candidate_input.destination_id is not None:
        codes.append("anchored")
    if score_breakdown.get("weighted_theme_coverage", 0.0) > 0.0:
        codes.append("theme_match")
    if score_breakdown.get("distance_penalty", 0.0) > 0.0:
        codes.append("proximity")
    if context.candidate_input.congestion_pref in {"quiet", "neutral"}:
        codes.append("small_city_lean")
    if alternative_city is None:
        codes.append("no_alternative")
    return tuple(dict.fromkeys(codes))


def _annotate_city_rankings(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selected_city_id: str,
) -> tuple[dict[str, Any], ...]:
    annotated: list[dict[str, Any]] = []
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        payload = dict(ranking)
        payload["selected"] = city_id == selected_city_id
        annotated.append(payload)
    return tuple(annotated)
