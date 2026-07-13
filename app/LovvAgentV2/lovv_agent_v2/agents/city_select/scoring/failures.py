from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.tools.city_select_contracts import PrunedCityGroups
from lovv_agent_v2.agents.city_select.retrieval.flow import (
    city_select_failure_state,
    package_failure,
    retrieval_audit,
)

CLARIFYING_QUESTION = "현재 조건에 맞는 후보 도시를 찾지 못했습니다."


@dataclass(frozen=True, slots=True)
class ScoringFailureContext:
    context: Any
    pruned_groups: PrunedCityGroups | None
    retrieved_count: int
    merged_count: int


def no_city_after_theme_gate(
    failure_context: ScoringFailureContext,
) -> dict[str, dict[str, Any]]:
    eliminated = (
        tuple(failure_context.pruned_groups.eliminated_cities)
        if failure_context.pruned_groups
        else ()
    )
    return _failure_state(
        failure_context,
        failure_signal="no_city_after_theme_gate",
        survived_city_count=0,
        eliminated_cities=eliminated,
    )


def no_scored_city(
    failure_context: ScoringFailureContext,
) -> dict[str, dict[str, Any]]:
    pruned_groups = failure_context.pruned_groups
    survived_city_count = len(pruned_groups.survived_groups) if pruned_groups else 0
    eliminated_cities = tuple(pruned_groups.eliminated_cities) if pruned_groups else ()
    return _failure_state(
        failure_context,
        failure_signal="no_scored_city",
        survived_city_count=survived_city_count,
        eliminated_cities=eliminated_cities,
    )


def _failure_state(
    failure_context: ScoringFailureContext,
    *,
    failure_signal: str,
    survived_city_count: int,
    eliminated_cities: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    fail_pkg = package_failure(
        failure_context.context,
        status="no_candidate",
        failure_signal=failure_signal,
        retrieval_audit=retrieval_audit(
            context=failure_context.context,
            retrieved_count=failure_context.retrieved_count,
            merged_count=failure_context.merged_count,
            survived_city_count=survived_city_count,
            eliminated_cities=eliminated_cities,
        ),
        needs_clarification=True,
        clarifying_question=CLARIFYING_QUESTION,
    )
    return {"city_select": city_select_failure_state(fail_pkg)}
