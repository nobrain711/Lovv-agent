from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final


Exposure = str
WEATHER_SENSITIVE_EXPOSURES: Final = {"outdoor", "mixed"}
VALID_EXPOSURES: Final = {"indoor", "outdoor", "mixed", "unknown"}


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    known_count: int
    sensitive_count: int
    counts: Mapping[str, int]


def summarize_exposure(items: Sequence[Mapping[str, object]]) -> ExposureSummary:
    counts = {key: 0 for key in VALID_EXPOSURES}
    for item in items:
        counts[item_exposure(item)] += 1
    known_count = counts["indoor"] + counts["outdoor"] + counts["mixed"]
    sensitive_count = counts["outdoor"] + counts["mixed"]
    return ExposureSummary(
        known_count=known_count,
        sensitive_count=sensitive_count,
        counts=counts,
    )


def item_exposure(item: Mapping[str, object]) -> Exposure:
    value = _text(item.get("indoor_outdoor")) or _text(item.get("indoorOutdoor"))
    if value is None:
        details = item.get("details")
        if isinstance(details, Mapping):
            value = _text(details.get("indoor_outdoor")) or _text(details.get("indoorOutdoor"))
    if value is not None and value in VALID_EXPOSURES:
        return value
    if item.get("item_type") == "festival" or item.get("itemType") == "festival":
        return "outdoor"
    return "unknown"


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


__all__ = ["ExposureSummary", "item_exposure", "summarize_exposure"]
