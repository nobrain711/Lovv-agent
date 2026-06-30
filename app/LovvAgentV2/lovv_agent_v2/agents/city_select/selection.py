"""Candidate selection helper for primary and reserve attraction evidence.

This module owns deterministic title deduplication, theme quota filling, soft
max relaxation, and reserve construction. It does not score places, call AWS, or
write itinerary text.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.agents.city_select.scoring import PlaceScoreResult

TOOL_NAME = "CandidateSelectionHelper"

RESPONSIBILITY = "Select primary and reserve candidates from scored evidence."

# budget은 Planner가 후보를 slot으로 바꾸기 전 내부 evidence 양을 제한한다.
TRIP_CANDIDATE_BUDGETS: dict[str, tuple[int, int]] = {
    "daytrip": (6, 4),
    "2d1n": (10, 8),
    "3d2n": (14, 10),
    "4d3n": (18, 12),
    "5d4n": (18, 12),
}

TRIP_ITINERARY_PLACE_COUNTS: dict[str, int] = {
    # count는 현재 Planner slot template과 맞춘다.
    "daytrip": 3,
    "2d1n": 5,
    "3d2n": 8,
    "4d3n": 11,
    "5d4n": 14,
}


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    """Normalized scored candidate used by primary/reserve selection."""

    payload: Any
    place_id: str
    title: str | None
    theme_tags: tuple[str, ...]
    place_score: float
    assigned_theme: str | None = None

    def with_role(self, slot_role: str, assigned_theme: str | None) -> dict[str, Any]:
        """Return a serializable payload with selection fields attached."""

        if isinstance(self.payload, PlaceScoreResult):
            result = self.payload.to_dict()
        elif isinstance(self.payload, Mapping):
            result = dict(self.payload)
        else:
            result = {
                "place_id": self.place_id,
                "title": self.title,
                "theme_tags": list(self.theme_tags),
            }
        result["place_id"] = self.place_id
        result["place_score"] = self.place_score
        result["slot_role"] = slot_role
        result["assigned_theme"] = assigned_theme
        result["_assigned_theme"] = assigned_theme
        return result


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    """Primary/reserve selection output and internal quota audit."""

    primary: tuple[dict[str, Any], ...]
    reserve: tuple[dict[str, Any], ...]
    coverage_audit: dict[str, Any]
    deduplicated_candidates: tuple[SelectionCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable selection result."""

        return {
            "recommended_places": list(self.primary),
            "reserve_places": list(self.reserve),
            "coverage_audit": dict(self.coverage_audit),
            "deduplicated_candidates": [
                asdict(candidate) for candidate in self.deduplicated_candidates
            ],
        }


@dataclass(frozen=True, slots=True)
class CandidateSelectionHelper:
    """Facade for deterministic primary/reserve candidate selection."""

    def select_primary_with_theme_quotas(
        self,
        candidates: Sequence[Any],
        searchable_place_themes: Sequence[str],
        *,
        primary_budget: int,
        reserve_budget: int,
        required_themes: Sequence[str] | None = None,
        external_link_themes: Sequence[str] | None = None,
    ) -> CandidateSelectionResult:
        """Select primary and reserve candidates with quota audit."""

        return select_primary_with_theme_quotas(
            candidates,
            searchable_place_themes,
            primary_budget=primary_budget,
            reserve_budget=reserve_budget,
            required_themes=required_themes,
            external_link_themes=external_link_themes,
        )


def candidate_budgets_for_trip(trip_type: str) -> tuple[int, int]:
    """Return primary and reserve budgets for a supported trip type."""

    normalized = _required_text(trip_type, "trip_type")
    if normalized not in TRIP_CANDIDATE_BUDGETS:
        raise SchemaValidationError(f"unsupported trip_type: {normalized}")
    return TRIP_CANDIDATE_BUDGETS[normalized]


def itinerary_place_count_for_trip(trip_type: str) -> int:
    """Return the attraction slot count Planner must be able to fill."""

    normalized = _required_text(trip_type, "trip_type")
    if normalized not in TRIP_ITINERARY_PLACE_COUNTS:
        raise SchemaValidationError(f"unsupported trip_type: {normalized}")
    return TRIP_ITINERARY_PLACE_COUNTS[normalized]


def select_primary_with_theme_quotas(
    candidates: Sequence[Any],
    searchable_place_themes: Sequence[str],
    *,
    primary_budget: int,
    reserve_budget: int,
    required_themes: Sequence[str] | None = None,
    external_link_themes: Sequence[str] | None = None,
) -> CandidateSelectionResult:
    """Build primary and reserve lists from scored candidates."""

    primary_limit = _positive_int(primary_budget, "primary_budget")
    reserve_limit = _non_negative_int(reserve_budget, "reserve_budget")
    searchable_themes = _string_tuple(
        searchable_place_themes,
        "searchable_place_themes",
    )
    required_theme_list = _string_tuple(
        required_themes if required_themes is not None else searchable_themes,
        "required_themes",
    )
    external_theme_list = _string_tuple(
        external_link_themes if external_link_themes is not None else (),
        "external_link_themes",
    )
    normalized = sorted(
        (_coerce_candidate(candidate) for candidate in candidates),
        key=lambda candidate: candidate.place_score,
        reverse=True,
    )
    deduplicated, deduped_title_count = _deduplicate_by_title(normalized)
    if not searchable_themes:
        primary_candidates = deduplicated[:primary_limit]
        primary_assignments = {
            candidate.place_id: _first_theme(candidate, ())
            for candidate in primary_candidates
        }
        reserve_candidates = deduplicated[primary_limit:primary_limit + reserve_limit]
        reserve_assignments = {
            candidate.place_id: _first_theme(candidate, ())
            for candidate in reserve_candidates
        }
        return _selection_result(
            primary_candidates=tuple(primary_candidates),
            reserve_candidates=tuple(reserve_candidates),
            primary_assignments=primary_assignments,
            reserve_assignments=reserve_assignments,
            deduplicated_candidates=tuple(deduplicated),
            required_themes=required_theme_list,
            searchable_themes=searchable_themes,
            external_link_themes=external_theme_list,
            theme_min_quota=0,
            theme_max_quota=0,
            min_quota_shortfalls={},
            max_quota_relaxed=False,
            relaxed_slots=0,
            deduplicated_title_count=deduped_title_count,
            primary_budget=primary_limit,
            reserve_budget=reserve_limit,
        )

    theme_min_quota = math.floor(primary_limit / len(searchable_themes) * 0.6)
    theme_max_quota = math.ceil(primary_limit / 2)
    selected: list[SelectionCandidate] = []
    selected_ids: set[str] = set()
    primary_assignments: dict[str, str | None] = {}
    theme_counts: Counter[str] = Counter()
    min_quota_shortfalls: dict[str, int] = {}

    for theme in searchable_themes:
        matching = [
            candidate
            for candidate in deduplicated
            if candidate.place_id not in selected_ids and theme in candidate.theme_tags
        ]
        taken = 0
        for candidate in matching:
            if taken >= theme_min_quota or len(selected) >= primary_limit:
                break
            selected.append(candidate)
            selected_ids.add(candidate.place_id)
            primary_assignments[candidate.place_id] = theme
            theme_counts[theme] += 1
            taken += 1
        shortfall = max(theme_min_quota - taken, 0)
        if shortfall:
            min_quota_shortfalls[theme] = shortfall

    for candidate in deduplicated:
        if len(selected) >= primary_limit:
            break
        if candidate.place_id in selected_ids:
            continue
        assigned_theme = _best_assignable_theme(
            candidate,
            searchable_themes,
            theme_counts,
            theme_max_quota,
            enforce_max=True,
        )
        if assigned_theme is None:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.place_id)
        primary_assignments[candidate.place_id] = assigned_theme
        theme_counts[assigned_theme] += 1

    relaxed_slots = 0
    if len(selected) < primary_limit:
        for candidate in deduplicated:
            if len(selected) >= primary_limit:
                break
            if candidate.place_id in selected_ids:
                continue
            assigned_theme = _best_assignable_theme(
                candidate,
                searchable_themes,
                theme_counts,
                theme_max_quota,
                enforce_max=False,
            )
            if assigned_theme is None:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.place_id)
            primary_assignments[candidate.place_id] = assigned_theme
            theme_counts[assigned_theme] += 1
            relaxed_slots += 1

    reserve_candidates = [
        candidate
        for candidate in deduplicated
        if candidate.place_id not in selected_ids
    ][:reserve_limit]
    reserve_assignments = {
        candidate.place_id: _first_theme(candidate, searchable_themes)
        for candidate in reserve_candidates
    }
    return _selection_result(
        primary_candidates=tuple(selected),
        reserve_candidates=tuple(reserve_candidates),
        primary_assignments=primary_assignments,
        reserve_assignments=reserve_assignments,
        deduplicated_candidates=tuple(deduplicated),
        required_themes=required_theme_list,
        searchable_themes=searchable_themes,
        external_link_themes=external_theme_list,
        theme_min_quota=theme_min_quota,
        theme_max_quota=theme_max_quota,
        min_quota_shortfalls=min_quota_shortfalls,
        max_quota_relaxed=relaxed_slots > 0,
        relaxed_slots=relaxed_slots,
        deduplicated_title_count=deduped_title_count,
        primary_budget=primary_limit,
        reserve_budget=reserve_limit,
    )


def _selection_result(
    *,
    primary_candidates: tuple[SelectionCandidate, ...],
    reserve_candidates: tuple[SelectionCandidate, ...],
    primary_assignments: Mapping[str, str | None],
    reserve_assignments: Mapping[str, str | None],
    deduplicated_candidates: tuple[SelectionCandidate, ...],
    required_themes: tuple[str, ...],
    searchable_themes: tuple[str, ...],
    external_link_themes: tuple[str, ...],
    theme_min_quota: int,
    theme_max_quota: int,
    min_quota_shortfalls: Mapping[str, int],
    max_quota_relaxed: bool,
    relaxed_slots: int,
    deduplicated_title_count: int,
    primary_budget: int,
    reserve_budget: int,
) -> CandidateSelectionResult:
    """Build selection payload and audit from normalized candidates."""

    primary = tuple(
        candidate.with_role("primary", primary_assignments.get(candidate.place_id))
        for candidate in primary_candidates
    )
    reserve = tuple(
        candidate.with_role("reserve", reserve_assignments.get(candidate.place_id))
        for candidate in reserve_candidates
    )
    primary_theme_counts = _theme_counts(primary, searchable_themes)
    reserve_theme_counts = _theme_counts(reserve, searchable_themes)
    unfilled_primary_slots = max(primary_budget - len(primary_candidates), 0)
    coverage_audit = {
        "required_themes": list(required_themes),
        "searchable_place_themes": list(searchable_themes),
        "external_link_themes": list(external_link_themes),
        "primary_theme_counts": primary_theme_counts,
        "reserve_theme_counts": reserve_theme_counts,
        "planner_capacity": (
            "sufficient" if len(primary_candidates) >= 5 else "insufficient"
        ),
        "theme_min_quota": theme_min_quota,
        "theme_max_quota": theme_max_quota,
        "min_quota_shortfalls": dict(min_quota_shortfalls),
        "max_quota_relaxed": max_quota_relaxed,
        "relaxed_slots": relaxed_slots,
        "deduplicated_title_count": deduplicated_title_count,
        "unfilled_primary_slots": unfilled_primary_slots,
        "primary_budget": primary_budget,
        "reserve_budget": reserve_budget,
    }
    return CandidateSelectionResult(
        primary=primary,
        reserve=reserve,
        coverage_audit=coverage_audit,
        deduplicated_candidates=deduplicated_candidates,
    )


def _deduplicate_by_title(
    candidates: Sequence[SelectionCandidate],
) -> tuple[list[SelectionCandidate], int]:
    """Deduplicate candidates by normalized title, preserving higher score first."""

    seen_titles: set[str] = set()
    deduplicated: list[SelectionCandidate] = []
    deduped = 0
    for candidate in candidates:
        key = _title_key(candidate.title)
        if key is None:
            deduplicated.append(candidate)
            continue
        if key in seen_titles:
            deduped += 1
            continue
        seen_titles.add(key)
        deduplicated.append(candidate)
    return deduplicated, deduped


def _coerce_candidate(candidate: Any) -> SelectionCandidate:
    """Normalize dicts, scoring results, and simple objects for selection."""

    if isinstance(candidate, SelectionCandidate):
        return candidate
    if isinstance(candidate, PlaceScoreResult):
        return SelectionCandidate(
            payload=candidate,
            place_id=candidate.place_id,
            title=candidate.title,
            theme_tags=candidate.theme_tags,
            place_score=candidate.place_score,
        )
    if isinstance(candidate, Mapping):
        return SelectionCandidate(
            payload=candidate,
            place_id=_required_text(_mapping_get(candidate, "place_id", "placeId"), "place_id"),
            title=_optional_text(_mapping_get(candidate, "title", "name", default=None)),
            theme_tags=_string_tuple(
                _mapping_get(candidate, "theme_tags", "themeTags", default=()),
                "theme_tags",
            ),
            place_score=_numeric(_mapping_get(candidate, "place_score", "score"), "place_score"),
        )
    return SelectionCandidate(
        payload=candidate,
        place_id=_required_text(
            _object_get(candidate, "place_id", "placeId", "id"),
            "place_id",
        ),
        title=_optional_text(_object_get(candidate, "title", "name")),
        theme_tags=_string_tuple(_object_get(candidate, "theme_tags", "themeTags"), "theme_tags"),
        place_score=_numeric(_object_get(candidate, "place_score", "score"), "place_score"),
    )


def _best_assignable_theme(
    candidate: SelectionCandidate,
    searchable_themes: tuple[str, ...],
    theme_counts: Counter[str],
    theme_max_quota: int,
    *,
    enforce_max: bool,
) -> str | None:
    """Choose one quota theme for a possibly multi-tag candidate."""

    matching = tuple(theme for theme in searchable_themes if theme in candidate.theme_tags)
    if not matching:
        return None
    allowed = (
        tuple(theme for theme in matching if theme_counts[theme] < theme_max_quota)
        if enforce_max
        else matching
    )
    if not allowed:
        return None
    return min(allowed, key=lambda theme: (theme_counts[theme], searchable_themes.index(theme)))


def _first_theme(
    candidate: SelectionCandidate,
    searchable_themes: tuple[str, ...],
) -> str | None:
    """Return the first matching searchable theme for audit assignment."""

    for theme in searchable_themes:
        if theme in candidate.theme_tags:
            return theme
    return candidate.theme_tags[0] if candidate.theme_tags else None


def _theme_counts(
    selected_payloads: Sequence[Mapping[str, Any]],
    searchable_themes: tuple[str, ...],
) -> dict[str, int]:
    """Count assigned themes for selected payloads."""

    counts = {theme: 0 for theme in searchable_themes}
    for payload in selected_payloads:
        assigned_theme = payload.get("assigned_theme")
        if assigned_theme in counts:
            counts[str(assigned_theme)] += 1
    return counts


def _title_key(title: str | None) -> str | None:
    """Normalize title for deduplication."""

    if title is None:
        return None
    normalized = title.strip().casefold()
    return normalized or None


def _mapping_get(
    payload: Mapping[str, Any],
    *field_names: str,
    default: Any = None,
) -> Any:
    """Return the first present field from a mapping."""

    for field_name in field_names:
        if field_name in payload:
            return payload[field_name]
    return default


def _object_get(value: Any, *field_names: str) -> Any:
    """Return the first present object attribute."""

    for field_name in field_names:
        if hasattr(value, field_name):
            return getattr(value, field_name)
    return None


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate and normalize a string sequence."""

    if value is None:
        return ()
    if isinstance(value, str):
        return (_required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty text value."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any) -> str | None:
    """Normalize optional text, treating blank strings as missing."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional text must be a string")
    normalized = value.strip()
    return normalized or None


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer input."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    """Validate a non-negative integer input."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise SchemaValidationError(f"{field_name} must be a non-negative integer")
    return value


def _numeric(value: Any, field_name: str) -> float:
    """Validate a numeric input."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


__all__ = [
    "CandidateSelectionHelper",
    "CandidateSelectionResult",
    "RESPONSIBILITY",
    "SelectionCandidate",
    "TOOL_NAME",
    "TRIP_CANDIDATE_BUDGETS",
    "TRIP_ITINERARY_PLACE_COUNTS",
    "candidate_budgets_for_trip",
    "itinerary_place_count_for_trip",
    "select_primary_with_theme_quotas",
]
