from __future__ import annotations

"""Scoring & Selection Node."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.models.schemas import SelectedCity, SchemaValidationError, CitySelectionResult
from lovv_agent_v2.agents.city_select.scoring import ScoringTool, PlaceScoreResult
from lovv_agent_v2.agents.city_select.selection import CandidateSelectionHelper, candidate_budgets_for_trip, itinerary_place_count_for_trip
from lovv_agent_v2.agents.city_select.retrieval_node import AttractionCandidate, CitySelectContext, _allowed_city_pk, _city_select_failure_state, _package_failure, _retrieval_audit

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
_VIBRANT_KEYWORDS = ("vibrant", "활기", "핫플", "축제", "복잡", "인기", "사람 많은", "핫플레이스")
_QUIET_KEYWORDS = ("quiet", "한적", "조용", "힐링", "고즈넉", "평화", "평온", "아늑", "휴식", "쉼")



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



def _lightweight_selected_places(
    selected_payloads: Sequence[Mapping[str, Any]],
    scored_places: Sequence[PlaceScoreResult],
) -> tuple[dict[str, Any], ...]:
    """Return selected candidates without raw retrieval payloads or details."""

    scored_by_id = {place.place_id: place for place in scored_places}
    result: list[dict[str, Any]] = []
    for payload in selected_payloads:
        place_id = _mapping_text(payload, "place_id")
        scored = scored_by_id[place_id]
        result.append(
            {
                "place_id": scored.place_id,
                "title": scored.title,
                "city_id": scored.city_id,
                "city_name_ko": _candidate_attr(scored.place, "city_name_ko"),
                "theme_tags": list(scored.theme_tags),
                "latitude": scored.latitude,
                "longitude": scored.longitude,
                "ddb_pk": _candidate_attr(scored.place, "ddb_pk"),
                "ddb_sk": _candidate_attr(scored.place, "ddb_sk"),
                "slot_role": payload.get("slot_role"),
                "assigned_theme": payload.get("assigned_theme"),
                "score_audit": {
                    "place_score": scored.place_score,
                    "score_components": dict(scored.score_components),
                },
            },
        )
    return tuple(result)



def _select_city_rank_index(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    fixed_city_id: str | None,
) -> int:
    """Select the highest-ranked city. In V2, capacity-based demotion is removed, so it always returns 0."""

    return 0


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


def _mapping_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _ddb_pk_from_group(city_id: str, scored_places: Sequence[PlaceScoreResult]) -> str:
    for place in scored_places:
        ddb_pk = _candidate_attr(place.place, "ddb_pk")
        if ddb_pk is not None:
            return str(ddb_pk).strip().upper()
    return city_id.strip().upper()


def _representative_seed_payload(place: PlaceScoreResult) -> dict[str, Any]:
    theme = place.theme_tags[0] if place.theme_tags else None
    subtype = _candidate_attr(place.place, "subtype_name") or _candidate_attr(
        place.place,
        "subtype",
    )
    return {
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "theme": theme,
        "sim": place.score_components.get("raw_similarity", 0.0),
        "lat": place.latitude,
        "lon": place.longitude,
        "subtype": subtype,
    }

def _seed_payload(place: PlaceScoreResult, theme: str) -> dict[str, Any]:
    subtype = _candidate_attr(place.place, "subtype_name") or _candidate_attr(
        place.place,
        "subtype",
    )
    return {
        "theme": theme,
        "place_id": place.place_id,
        "ddb_sk": _candidate_attr(place.place, "ddb_sk"),
        "title": place.title,
        "sim": place.score_components.get("raw_similarity", 0.0),
        "lat": place.latitude,
        "lon": place.longitude,
        "subtype": subtype,
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
            "ddb_pk": _ddb_pk_from_group(city_id, scored_places),
            "city_name_ko": ranking.get("city_name_ko"),
            "score_delta": round(selected_score - float(ranking["city_score"]), 4),
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
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    selected_city_id: str,
) -> tuple[dict[str, Any], ...]:
    """Attach itinerary-capacity audit fields to each city ranking."""

    annotated: list[dict[str, Any]] = []
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        selected = selection_by_city[city_id]
        available_place_count = len(selected.primary)
        payload = dict(ranking)
        payload.update(
            {
                "available_place_count": available_place_count,
                "required_place_count": required_place_count,
                "itinerary_sufficient": available_place_count >= required_place_count,
                "selected": city_id == selected_city_id,
            },
        )
        annotated.append(payload)
    return tuple(annotated)



def _itinerary_coverage_audit(
    coverage_audit: Mapping[str, Any],
    *,
    required_place_count: int,
    available_place_count: int,
) -> dict[str, Any]:
    """Extend quota audit with primary-only Planner capacity."""

    result = dict(coverage_audit)
    result.update(
        {
            "itinerary_required_place_count": required_place_count,
            "available_place_count": available_place_count,
            "reserve_places_considered": False,
            "itinerary_sufficiency": (
                "sufficient"
                if available_place_count >= required_place_count
                else "insufficient"
            ),
        },
    )
    return result



def _status_from_selection(
    *,
    required_place_count: int,
    available_place_count: int,
) -> str:
    """Return package status from Planner-facing itinerary capacity."""

    if available_place_count < required_place_count:
        return "insufficient_candidates"
    return "ok"



def _selected_city(
    city_id: str,
    scored_places: Sequence[PlaceScoreResult],
    *,
    context: CitySelectContext,
    status: str,
    selected_rank_index: int,
) -> SelectedCity:
    """Build the selected city summary for Planner input."""

    reason_codes = (
        ["anchored_city"]
        if context.candidate_input.destination_id
        else [f"city_score_rank_{selected_rank_index + 1}"]
    )
    if selected_rank_index > 0:
        reason_codes.append("itinerary_capacity_fallback")
    if status == "ok":
        reason_codes.append("planner_capacity_sufficient")
    else:
        reason_codes.append("insufficient_candidates")
    province = _candidate_attr(scored_places[0].place, "province") or _candidate_attr(
        scored_places[0].place,
        "location",
    )
    return SelectedCity(
        city_id=_candidate_attr(scored_places[0].place, "city_id") or city_id,
        city_name_ko=_city_name_from_group(scored_places) or city_id,
        country=context.candidate_input.country,
        selection_reason_code=tuple(reason_codes),
        ddb_pk=_ddb_pk_from_group(city_id, scored_places),
        province=province,
    )



from lovv_agent_v2.core.state import UnifiedAgentState

def scoring_and_selection_node(state: UnifiedAgentState) -> dict:
    """Score candidates, apply soft gates, extract seed, evaluate transport_pref."""
    # 1. 런타임에 인프라와 도구 빌드
    from lovv_agent_v2.infra.config import RuntimeConfig
    from lovv_agent_v2.infra.aws_clients import AwsClientProvider, create_boto3_client_factory
    from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
    from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool

    config = RuntimeConfig.from_env()
    client_factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    client_provider = AwsClientProvider.from_factory(client_factory, config=config)
    dynamo_repo = DynamoDbRepository(
        client=client_provider.create_dynamodb_client(),
        settings=config.dynamodb,
    )
    dynamo_lookup = DynamoLookupTool(dynamodb=dynamo_repo, search_budget=config.search_budget)

    scoring = ScoringTool()
    selection = CandidateSelectionHelper()

    # 2. State에서 retrieval 노드의 산출물 로드
    city_select_state = state.get("city_select", {}) if isinstance(state, dict) else getattr(state, "city_select", {})
    if not city_select_state or "pruned_groups" not in city_select_state:
        # 이전 노드에서 이미 실패 패키지가 생성되어 바로 반환되었을 경우 회피
        return {}

    pruned_groups = city_select_state.get("pruned_groups")
    festival_seed_result = city_select_state.get("festival_seed_result")
    context = city_select_state.get("context")
    retrieved_count = city_select_state.get("retrieved_count", 0)
    merged_count = city_select_state.get("merged_count", 0)

    # pruned_groups가 비었거나 실패 시 처리
    if not pruned_groups or not pruned_groups.survived_groups:
        fail_pkg = _package_failure(
            context,
            status="no_candidate",
            failure_signal="no_city_after_theme_gate",
            retrieval_audit=_retrieval_audit(
                context=context,
                retrieved_count=retrieved_count,
                merged_count=merged_count,
                survived_city_count=0,
                eliminated_cities=tuple(pruned_groups.eliminated_cities) if pruned_groups else (),
            ),
            needs_clarification=True,
            clarifying_question="현재 조건에 맞는 후보 도시를 찾지 못했습니다.",
        )
        return {"city_select": _city_select_failure_state(fail_pkg)}

    # 3. 스코어링 및 랭킹 산출 (V1 run 뒷단 이식)
    primary_budget, reserve_budget = candidate_budgets_for_trip(
        context.candidate_input.trip_type,
    )
    scored_groups = _score_groups(
        pruned_groups.survived_groups,
        context=context,
        scoring=scoring,
    )
    city_rankings = _rank_cities(
        scored_groups,
        context=context,
        scoring=scoring,
        primary_budget=primary_budget,
        dynamo_lookup=dynamo_lookup,
    )

    if not city_rankings:
        fail_pkg = _package_failure(
            context,
            status="no_candidate",
            failure_signal="no_scored_city",
            retrieval_audit=_retrieval_audit(
                context=context,
                retrieved_count=retrieved_count,
                merged_count=merged_count,
                survived_city_count=len(pruned_groups.survived_groups),
                eliminated_cities=tuple(pruned_groups.eliminated_cities),
            ),
            needs_clarification=True,
            clarifying_question="현재 조건에 맞는 후보 도시를 찾지 못했습니다.",
        )
        return {"city_select": _city_select_failure_state(fail_pkg)}

    required_place_count = itinerary_place_count_for_trip(
        context.candidate_input.trip_type,
    )
    selection_by_city = {
        ranking["city_id"]: selection.select_primary_with_theme_quotas(
            scored_groups[ranking["city_id"]],
            context.theme_split.searchable_place_themes,
            primary_budget=primary_budget,
            reserve_budget=reserve_budget,
            required_themes=context.theme_split.active_required_themes,
            external_link_themes=context.theme_split.external_link_themes,
        )
        for ranking in city_rankings
    }
    selected_rank_index = _select_city_rank_index(
        city_rankings,
        selection_by_city=selection_by_city,
        required_place_count=required_place_count,
        fixed_city_id=context.candidate_input.destination_id,
    )
    selected_city_id = city_rankings[selected_rank_index]["city_id"]
    selected_group = scored_groups[selected_city_id]
    selected_places = selection_by_city[selected_city_id]
    recommended_places = _lightweight_selected_places(selected_places.primary, selected_group)
    reserve_places = _lightweight_selected_places(selected_places.reserve, selected_group)
    available_place_count = len(recommended_places)
    
    coverage_audit = _itinerary_coverage_audit(
        selected_places.coverage_audit,
        required_place_count=required_place_count,
        available_place_count=available_place_count,
    )
    status = _status_from_selection(
        required_place_count=required_place_count,
        available_place_count=available_place_count,
    )
    selected_city = _selected_city(
        selected_city_id,
        selected_group,
        context=context,
        status=status,
        selected_rank_index=selected_rank_index,
    )
    annotated_rankings = _annotate_city_rankings(
        city_rankings,
        selection_by_city=selection_by_city,
        required_place_count=required_place_count,
        selected_city_id=selected_city_id,
    )

    # V2_15_TASK1: 대표 시드(representative_seed) - 선택 도시 내 place_score 최고 1개 장소 추출
    representative_seed_result = max(selected_group, key=lambda p: p.place_score)
    representative_seed = _representative_seed_payload(representative_seed_result)

    # V2_15_TASK1: 각 테마별 실검출 관광지 개수 요약
    theme_counts = {}
    for place in selected_group:
        for theme in place.theme_tags:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
    theme_evidence_summary = {
        theme: count
        for theme, count in theme_counts.items()
        if theme in context.theme_split.searchable_place_themes
    }

    # V2_15_TASK1: 누락 테마 목록 추출
    missing_themes = pruned_groups.missing_themes_by_city.get(selected_city_id, ()) if pruned_groups and pruned_groups.missing_themes_by_city else ()

    # V2_15_TASK1: 선택된 도시의 점수 상세 breakdown 정보
    selected_ranking = next(r for r in city_rankings if r["city_id"] == selected_city_id)
    score_breakdown = selected_ranking.get("score_breakdown", {})
    alternative_city = _alternative_city_payload(
        city_rankings,
        scored_groups,
        selected_city_id=selected_city_id,
    )
    seeds = _seed_payloads(
        selected_group,
        context.theme_split.searchable_place_themes,
    )

    retrieval_audit = _retrieval_audit(
        context=context,
        retrieved_count=retrieved_count,
        merged_count=merged_count,
        survived_city_count=len(pruned_groups.survived_groups),
        eliminated_cities=tuple(pruned_groups.eliminated_cities),
    )

    # V2_15_TASK1: Planner 핸드오프용 힌트 구성
    planner_hints = {
        "primary_budget": primary_budget,
        "reserve_budget": reserve_budget,
        "required_place_count": required_place_count,
        "itinerary_sufficiency": coverage_audit.get("itinerary_sufficiency", "sufficient"),
    }

    # V2_15_TASK1: CitySelectionResult 핸드오프 규격 구성 (DTO 인스턴스화)
    city_selection_result = CitySelectionResult(
        selected_city=selected_city,
        alternative_city=alternative_city,
        selection_reason_code=_selection_reason_codes(
            context=context,
            score_breakdown=score_breakdown,
            alternative_city=alternative_city,
        ),
        representative_seed=representative_seed,
        seeds=seeds,
        headline_seed=_headline_seed(seeds),
        theme_evidence=_theme_evidence_payload(
            selected_group,
            context.theme_split.searchable_place_themes,
        ),
        theme_evidence_summary=theme_evidence_summary,
        missing_themes=tuple(missing_themes),
        passthrough=_passthrough_payload(context),
        score_breakdown=score_breakdown,
        retrieval_audit=retrieval_audit,
        planner_hints=planner_hints,
    )

    # 4. 최종 패키지 구성 (V2 clean drop: reason_claims 제거)
    def _festival_payloads(seed_res, cid=None):
        if not seed_res or not seed_res.candidates:
            return []
        return [
            cand.to_dict()
            for cand in seed_res.candidates
            if cid is None or cand.city_id == cid
        ]

    candidate_counts = {
        "retrieved": retrieved_count,
        "merged": merged_count,
        "scored": sum(len(group) for group in scored_groups.values()),
        "city_count": len(city_rankings),
        "recommended_places": len(recommended_places),
        "reserve_places": len(reserve_places),
        "available_places": available_place_count,
        "required_itinerary_places": required_place_count,
        "reserve_places_considered_for_itinerary": False,
    }
    fallback_audit = {
        "planner_consumable": True,
        "status_reason": status,
        "festival_seed_applied": festival_seed_result is not None,
        "selected_city_rank": selected_rank_index + 1,
        "city_reselected_for_itinerary_capacity": selected_rank_index > 0,
    }

    return {
        "city_select": {
            "city_selection_result": city_selection_result.to_dict(),
            "status": status,
            "clarification": None,
            "retrieval_audit": retrieval_audit,
            "scoring_audit": {
                "city_rankings": annotated_rankings,
                "recommended_places": recommended_places,
                "reserve_places": reserve_places,
                "festival_candidates": _festival_payloads(festival_seed_result),
                "selected_festival_candidates": _festival_payloads(
                    festival_seed_result,
                    city_id=None if context.candidate_input.destination_id is not None else selected_city_id,
                ),
                "festival_seed_audit": (
                    _retrieval_audit(
                        context=context,
                        retrieved_count=retrieved_count,
                        merged_count=merged_count,
                        survived_city_count=len(pruned_groups.survived_groups),
                        eliminated_cities=tuple(pruned_groups.eliminated_cities),
                    )
                    if festival_seed_result
                    else {}
                ),
                "coverage_audit": coverage_audit,
                "candidate_counts": candidate_counts,
                "fallback_audit": fallback_audit,
            },
            "selected_destination": selected_city.to_dict() if selected_city else None,
        }
    }
