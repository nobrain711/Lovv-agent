from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONFIRMATION_INTENT_VALUES = frozenset(
    {
        "itinerary_confirmed",
        "itinerary_confirmation",
        "confirm_itinerary",
        "confirm",
        "confirmed",
        "일정_확정",
    },
)
CONFIRMATION_FIELD_NAMES = (
    "intent_type",
    "intentType",
    "action",
    "entry_type",
    "entryType",
)


def is_itinerary_confirmation_state(state: Mapping[str, Any]) -> bool:
    for group_name in ("intent", "request"):
        group = state.get(group_name)
        if isinstance(group, Mapping) and _is_itinerary_confirmation(group):
            return True
    return False


def _is_itinerary_confirmation(payload: Mapping[str, Any]) -> bool:
    return any(
        _normalized_intent_value(payload.get(field_name)) in CONFIRMATION_INTENT_VALUES
        for field_name in CONFIRMATION_FIELD_NAMES
    )


def _normalized_intent_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")
