from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lovv_agent_v2.agents.intent.parser import parse_initial_query
from lovv_agent_v2.agents.intent.region_resolver import resolve_region_preferences


def canonical_prompt_region_updates(
    *,
    raw_query: str,
    preferred_spans: Sequence[str],
    disliked_spans: Sequence[str],
) -> dict[str, Any]:
    rule_preference = parse_initial_query(raw_query)
    prompt_preferred_spans = _remove_rule_opposites(
        preferred_spans,
        raw_query=raw_query,
        opposite_ids=rule_preference.disliked_region_ids,
        same_ids=rule_preference.preferred_region_ids,
    )
    prompt_disliked_spans = _remove_rule_opposites(
        disliked_spans,
        raw_query=raw_query,
        opposite_ids=rule_preference.preferred_region_ids,
        same_ids=rule_preference.disliked_region_ids,
    )
    resolution = resolve_region_preferences(
        preferred_spans=(
            *rule_preference.preferred_region_spans,
            *prompt_preferred_spans,
        ),
        disliked_spans=(
            *rule_preference.disliked_region_spans,
            *prompt_disliked_spans,
        ),
        raw_query=raw_query,
    )
    return {
        "preferred_region_ids": resolution.preferred_region_ids,
        "disliked_region_ids": resolution.disliked_region_ids,
        "preferred_region_names": resolution.preferred_region_names,
        "disliked_region_names": resolution.disliked_region_names,
        "preferred_region_spans": resolution.preferred_region_spans,
        "disliked_region_spans": resolution.disliked_region_spans,
        "unresolved_region_spans": resolution.unresolved_region_spans,
    }


def _remove_rule_opposites(
    spans: Sequence[str],
    *,
    raw_query: str,
    opposite_ids: Sequence[str],
    same_ids: Sequence[str],
) -> tuple[str, ...]:
    excluded_ids = set(opposite_ids).difference(same_ids)
    if not excluded_ids:
        return tuple(spans)
    return tuple(
        span
        for span in spans
        if excluded_ids.isdisjoint(
            resolve_region_preferences(
                preferred_spans=(span,),
                disliked_spans=(),
                raw_query=raw_query,
            ).preferred_region_ids,
        )
    )


__all__ = ["canonical_prompt_region_updates"]
