from __future__ import annotations

from typing import Any, Final

INTENT_PROMPT_SCHEMA_NAME: Final = "lovv_v2_intent_output"
_REQUIRED_FIELDS: Final = (
    "cleaned_raw_query",
    "soft_preference_query",
    "unsupported_conditions",
    "congestion_pref",
    "transport_pref",
    "preferred_theme_ids",
    "disliked_theme_ids",
    "preferred_region_spans",
    "disliked_region_spans",
    "needs_clarification",
    "clarifying_question",
    "contradiction_reasons",
)
_THEME_ID_ENUM: Final = (
    "sea_coast",
    "nature_trekking",
    "history_tradition",
    "art_sense",
    "healing_rest",
    "food_local",
)
INTENT_PROMPT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_REQUIRED_FIELDS),
    "properties": {
        "cleaned_raw_query": {"type": "string"},
        "soft_preference_query": {"type": "string"},
        "unsupported_conditions": {"type": "array", "items": {"type": "string"}},
        "congestion_pref": {"type": "string", "enum": ["quiet", "vibrant", "neutral"]},
        "transport_pref": {"type": "string", "enum": ["walk", "car", "unknown"]},
        "preferred_theme_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_THEME_ID_ENUM)},
        },
        "disliked_theme_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(_THEME_ID_ENUM)},
        },
        "preferred_region_spans": {"type": "array", "items": {"type": "string"}},
        "disliked_region_spans": {"type": "array", "items": {"type": "string"}},
        "needs_clarification": {"type": "boolean"},
        "clarifying_question": {"type": ["string", "null"]},
        "contradiction_reasons": {"type": "array", "items": {"type": "string"}},
    },
}

__all__ = ["INTENT_PROMPT_OUTPUT_SCHEMA", "INTENT_PROMPT_SCHEMA_NAME"]
