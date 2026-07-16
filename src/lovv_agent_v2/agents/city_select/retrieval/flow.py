from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lovv_agent_v2.common.telemetry_threading import submit_with_context
from lovv_agent_v2.tools.city_select_contracts import (
    AttractionCandidate,
    CitySelectContext,
)
from lovv_agent_v2.tools.destination_policy import allowed_city_pk
from lovv_agent_v2.models.schemas import CitySelectResult, SchemaValidationError


def retrieve_by_theme(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    city_id: str | None,
    ddb_pk: str | None = None,
    preferred_city_ids: Sequence[str] = (),
    disliked_city_ids: Sequence[str] = (),
) -> tuple[AttractionCandidate, ...]:
    all_theme_candidates: dict[str, list[AttractionCandidate]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(themes))) as executor:
        raw_futures = {}
        for theme in themes:
            if preferred_city_ids or disliked_city_ids:
                future = submit_with_context(
                    executor,
                    lambda theme=theme: destination_search.search_candidates(
                        query_vector,
                        city_id=city_id,
                        ddb_pk=ddb_pk,
                        theme=theme,
                        preferred_city_ids=preferred_city_ids,
                        disliked_city_ids=disliked_city_ids,
                    ),
                )
            else:
                future = submit_with_context(
                    executor,
                    lambda theme=theme: destination_search.search_candidates(
                        query_vector,
                        city_id=city_id,
                        ddb_pk=ddb_pk,
                        theme=theme,
                    ),
                )
            raw_futures[future] = theme
        for future, theme in raw_futures.items():
            all_theme_candidates[theme] = list(future.result())

    candidates: list[AttractionCandidate] = []
    for theme in themes:
        candidates.extend(all_theme_candidates.get(theme, []))
    return tuple(candidates)


def retrieve_allowed_city_pool_by_theme(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    allowed_city_ids: Sequence[str],
) -> tuple[AttractionCandidate, ...]:
    candidates: list[AttractionCandidate] = []
    for city_id in tuple(dict.fromkeys(allowed_city_ids)):
        candidates.extend(
            retrieve_by_theme(
                destination_search,
                query_vector=query_vector,
                themes=themes,
                city_id=city_id,
            ),
        )
    return tuple(candidates)


def merge_duplicate_candidates(
    candidates: Sequence[AttractionCandidate],
) -> tuple[AttractionCandidate, ...]:
    by_place_id: dict[str, AttractionCandidate] = {}
    for candidate in candidates:
        previous = by_place_id.get(candidate.place_id)
        if previous is None or candidate.distance < previous.distance:
            by_place_id[candidate.place_id] = candidate
    return tuple(by_place_id.values())


def package_failure(
    context: CitySelectContext,
    *,
    status: str,
    failure_signal: str,
    failure_signals: Sequence[str] | None = None,
    needs_clarification: bool,
    clarifying_question: str | None = None,
    retrieval_audit: Mapping[str, Any] | None = None,
) -> CitySelectResult:
    return CitySelectResult(
        status=status,
        failure_signals=tuple(failure_signals or (failure_signal,)),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
        mode=context.mode,
        city_anchor=None,
        festival_candidates=(),
        selected_festival_candidates=(),
        festival_seed_audit={},
        retrieval_audit=dict(retrieval_audit or {}),
        candidate_counts={},
        fallback_audit={
            "planner_consumable": False,
            "failure_signal": failure_signal,
            "festival_seed_applied": False,
        },
    )


def allowed_city_ids(
    *,
    context: CitySelectContext,
    allowed_city_ids: Sequence[str] | None,
) -> tuple[str, ...] | None:
    if allowed_city_ids is not None:
        normalized = tuple(dict.fromkeys(allowed_city_ids))
        return normalized or None
    if context.candidate_input.destination_id is not None:
        return (context.candidate_input.destination_id,)
    return None


def retrieval_audit(
    *,
    context: CitySelectContext,
    retrieved_count: int,
    merged_count: int,
    survived_city_count: int,
    eliminated_cities: Sequence[str],
) -> dict[str, Any]:
    return {
        "mode": context.mode,
        "searchable_place_themes": list(context.theme_split.searchable_place_themes),
        "no_support_themes": list(context.theme_split.no_support_themes),
        "fixed_city_id": context.candidate_input.destination_id,
        "retrieved_candidate_count": retrieved_count,
        "merged_candidate_count": merged_count,
        "survived_city_count": survived_city_count,
        "eliminated_cities": list(eliminated_cities),
    }


def city_select_failure_state(result: CitySelectResult) -> dict[str, Any]:
    return {
        "city_selection_result": None,
        "status": result.status,
        "clarification": None,
        "retrieval_audit": dict(result.retrieval_audit),
        "scoring_audit": {},
        "failure_signals": tuple(result.failure_signals),
        "fallback_audit": dict(result.fallback_audit),
        "clarifying_question": result.clarifying_question,
    }


def embedding_query_text(context: CitySelectContext) -> str:
    query = context.candidate_input.cleaned_raw_query.strip()
    if query:
        return query
    theme_query = " ".join(context.theme_split.searchable_place_themes)
    if theme_query:
        return theme_query
    raise SchemaValidationError("cleaned_raw_query is required for city_select embedding")


__all__ = [
    "allowed_city_ids",
    "allowed_city_pk",
    "city_select_failure_state",
    "embedding_query_text",
    "merge_duplicate_candidates",
    "package_failure",
    "retrieval_audit",
    "retrieve_allowed_city_pool_by_theme",
    "retrieve_by_theme",
]
