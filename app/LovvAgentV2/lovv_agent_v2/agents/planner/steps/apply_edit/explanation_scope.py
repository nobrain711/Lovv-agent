from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

EXPLANATION_MARKERS = (
    "planner_copy_generation_used_llm",
    "detail_enrichment_warning_count",
    "detail_enrichment_warnings",
    "itinerary_explanation_item_count",
    "modification_explanation_attempted",
    "modification_explanation_completed",
)


def explanation_place_ids(
    applied_edits: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    place_ids: list[str] = []
    for applied_edit in applied_edits:
        replacements = (
            _mapping_sequence(applied_edit.get("replacements"))
            or (_mapping(applied_edit.get("replacement")),)
        )
        for replacement in replacements:
            replacement_id = _optional_text(replacement.get("content_id"))
            if replacement_id is not None and replacement_id not in place_ids:
                place_ids.append(replacement_id)
    return tuple(place_ids)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
