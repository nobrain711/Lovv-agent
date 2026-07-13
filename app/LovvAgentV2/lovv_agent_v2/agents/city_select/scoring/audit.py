from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def theme_evidence_summary(selected_group: tuple[Any, ...], themes: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for place in selected_group:
        for theme in place.theme_tags:
            counts[theme] = counts.get(theme, 0) + 1
    return {theme: count for theme, count in counts.items() if theme in themes}


def scoring_audit(
    *,
    context: Any,
    annotated_rankings: tuple[dict[str, Any], ...],
    festival_seed_result: Any,
    selected_city_id: str,
    coverage_audit: Mapping[str, Any],
    candidate_counts: Mapping[str, Any],
    status: str,
    retrieval_audit: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "city_rankings": annotated_rankings,
        "festival_candidates": festival_payloads(festival_seed_result),
        "selected_festival_candidates": festival_payloads(
            festival_seed_result,
            city_id=None
            if context.candidate_input.destination_id is not None
            else selected_city_id,
        ),
        "festival_seed_audit": retrieval_audit if festival_seed_result else {},
        "coverage_audit": coverage_audit,
        "candidate_counts": dict(candidate_counts),
        "fallback_audit": {
            "planner_consumable": True,
            "status_reason": status,
            "festival_seed_applied": festival_seed_result is not None,
        },
    }


def festival_payloads(seed_result: Any, city_id: str | None = None) -> list[dict[str, Any]]:
    if not seed_result or not seed_result.candidates:
        return []
    return [
        candidate.to_dict()
        for candidate in seed_result.candidates
        if city_id is None or candidate.city_id == city_id
    ]
