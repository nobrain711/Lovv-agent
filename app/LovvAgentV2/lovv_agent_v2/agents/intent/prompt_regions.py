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
    resolution = resolve_region_preferences(
        preferred_spans=(*rule_preference.preferred_region_spans, *preferred_spans),
        disliked_spans=(*rule_preference.disliked_region_spans, *disliked_spans),
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


__all__ = ["canonical_prompt_region_updates"]
