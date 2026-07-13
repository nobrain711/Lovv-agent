from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult, ScoringTool
from lovv_agent_v2.tools.city_select_contracts import (
    AttractionCandidate,
    CitySelectContext,
)

def _score_groups(
    groups: Mapping[str, Sequence[AttractionCandidate]],
    *,
    context: CitySelectContext,
    scoring: ScoringTool,
) -> dict[str, tuple[PlaceScoreResult, ...]]:
    """Score each survived city's attraction candidates."""

    scored_groups: dict[str, tuple[PlaceScoreResult, ...]] = {}
    for city_id, candidates in groups.items():
        scored = tuple(
            result
            for candidate in candidates
            if (
                result := scoring.score_place(
                    candidate,
                    context.theme_split.searchable_place_themes,
                )
            ).scored
        )
        if scored:
            scored_groups[city_id] = scored
    return scored_groups


W_CONG_QUIET = 0.08
W_CONG_VIBRANT = -0.05
W_CONG_DEFAULT = 0.03



def _rank_cities(
    scored_groups: Mapping[str, Sequence[PlaceScoreResult]],
    *,
    context: CitySelectContext,
    scoring: ScoringTool,
    primary_budget: int,
    dynamo_lookup: Any | None = None,
) -> tuple[dict[str, Any], ...]:
    """Rank cities by deterministic city score (congestion 보정 포함)."""

    # 혼잡도 보정: 생존 도시 방문객을 1회 BatchGetItem으로 조회해 rank 정규화.
    # 조회/통계 실패는 추천을 막지 않고 congestion 비활성(0)으로 폴백한다.
    congestion_by_city: dict[str, float] = {}
    w_cong = 0.0
    city_ids = list(scored_groups.keys())
    if dynamo_lookup is not None and city_ids:
        try:
            # 전이기: STAT PK는 도시명 파티션(CITY#이름)이라 숫자 city_id로는 못 만든다.
            # candidate metadata의 ddb_pk(이름 보유)를 넘겨 조회 측에서 titlecase 정규화한다.
            pk_by_city = _ddb_pk_by_city(scored_groups)
            visitor_by_city = dynamo_lookup.city_visitor_stats(
                city_ids,
                context.candidate_input.travel_month,
                partition_key_by_city=pk_by_city,
            )
            congestion_by_city = _congestion_index_by_city(visitor_by_city)
            w_cong = resolve_w_cong(context.candidate_input.congestion_pref)
        except Exception:  # noqa: BLE001 - congestion은 보강 신호이므로 실패 시 중립.
            congestion_by_city = {}
            w_cong = resolve_w_cong(context.candidate_input.congestion_pref)

    rankings: list[dict[str, Any]] = []
    for city_id, places in scored_groups.items():
        city_score = scoring.score_city(
            city_id=city_id,
            places=places,
            active_themes=context.theme_split.searchable_place_themes,
            user_location=context.candidate_input.user_location,
            primary_budget=primary_budget,
            congestion_index=congestion_by_city.get(city_id, 0.5),
            w_cong=w_cong,
            theme_weights=context.candidate_input.theme_weights,
            trip_type=context.candidate_input.trip_type,
        )
        ranking = city_score.to_dict()
        ranking["city_name_ko"] = _city_name_from_group(places) or city_id
        rankings.append(ranking)
    return tuple(
        sorted(
            rankings,
            key=lambda item: (item["city_score"], item["candidate_count"]),
            reverse=True,
        ),
    )


def resolve_w_cong(congestion_pref: str) -> float:
    match congestion_pref:
        case "quiet":
            return W_CONG_QUIET
        case "vibrant":
            return W_CONG_VIBRANT
        case "neutral":
            return W_CONG_DEFAULT
        case _:
            return W_CONG_DEFAULT


def _congestion_index_by_city(visitor_by_city: Mapping[str, float | None]) -> dict[str, float]:
    known_values = {
        city_id: visitors
        for city_id, visitors in visitor_by_city.items()
        if visitors is not None and visitors > 0
    }
    if len(known_values) < 2:
        return {city_id: 0.5 for city_id in visitor_by_city}
    log_values = {city_id: math.log(visitors) for city_id, visitors in known_values.items()}
    minimum = min(log_values.values())
    maximum = max(log_values.values())
    if minimum == maximum:
        return {city_id: 0.5 for city_id in visitor_by_city}
    result = {city_id: 0.5 for city_id in visitor_by_city}
    for city_id, log_value in log_values.items():
        result[city_id] = (log_value - minimum) / (maximum - minimum)
    return result


def _ddb_pk_by_city(
    scored_groups: Mapping[str, Sequence[PlaceScoreResult]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for city_id, places in scored_groups.items():
        for place in places:
            ddb_pk = _candidate_attr(place.place, "ddb_pk")
            if ddb_pk is not None:
                result[city_id] = ddb_pk
                break
    return result


def _city_name_from_group(scored_places: Sequence[PlaceScoreResult]) -> str | None:
    for place in scored_places:
        city_name = _candidate_attr(place.place, "city_name_ko") or _candidate_attr(
            place.place,
            "city_name",
        )
        if city_name is not None:
            return city_name
    return None


def _candidate_attr(candidate: Any, field_name: str) -> Any | None:
    if isinstance(candidate, Mapping):
        value = candidate.get(field_name)
        if value is not None:
            return value
        metadata = candidate.get("metadata")
        if isinstance(metadata, Mapping):
            return metadata.get(field_name)
        return None
    value = getattr(candidate, field_name, None)
    if value is not None:
        return value
    metadata = getattr(candidate, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata.get(field_name)
    return None
