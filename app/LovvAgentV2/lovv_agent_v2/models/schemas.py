"""Schema contracts for Lovv agent handoff payloads.

Task 1.3 keeps schemas dependency-light by using standard-library dataclasses
and explicit validation helpers. The classes in this module define payloads
that cross node boundaries; they do not perform retrieval, scoring, planning,
or response packaging.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a graph payload violates the local schema contract."""


SCHEMA_GROUPS: tuple[str, ...] = (
    # 테스트와 결과 report에서 사용하는 public handoff schema 묶음이다.
    "CitySelectInput",
    "CitySelectResult",
    "FestivalVerification",
    "PlannerOutput",
    "BackendResponse",
)

CANDIDATE_EVIDENCE_STATUSES: tuple[str, ...] = (
    "ok",
    "insufficient_candidates",
    "no_candidate",
    "error",
)

EXECUTION_MODES: tuple[str, ...] = (
    "city_discovery",
    "anchored_place_search",
    "festival_seeded_city_discovery",
)

FESTIVAL_DATE_STATUSES: tuple[str, ...] = (
    "confirmed",
    "tentative",
    "unknown",
    "outdated",
    "skipped",
    "no_candidate",
)

PLANNER_POLICIES: tuple[str, ...] = (
    "placeable",
    "notice_only",
    "not_placeable",
    "skip",
)

_MISSING = object()
# sentinel은 mapping reader가 누락값과 명시적 None을 구분하게 해준다.


def _mapping_get(
    payload: Mapping[str, Any],
    *keys: str,
    default: Any = _MISSING,
) -> Any:
    """Read the first present key from a mapping.

    The helper lets schemas accept the current mixed camelCase/snake_case
    handoff examples while storing normalized snake_case attributes internally.
    """

    for key in keys:
        if key in payload:
            return payload[key]
    if default is not _MISSING:
        return default
    joined = " or ".join(keys)
    raise SchemaValidationError(f"missing required field: {joined}")


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty string value."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate an optional text value and normalize blanks to ``None``."""

    if value is None:
        return None
    return _required_text(value, field_name)


def _free_text(value: Any, field_name: str) -> str:
    """Validate a string field that may be empty."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    return value.strip()


def _required_int(value: Any, field_name: str) -> int:
    """Validate an integer value without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def _month(value: Any, field_name: str) -> int:
    """Validate a month number in the 1-12 range."""

    parsed = _required_int(value, field_name)
    if parsed < 1 or parsed > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return parsed


def _bool(value: Any, field_name: str) -> bool:
    """Validate a boolean value without truthy coercion."""

    if not isinstance(value, bool):
        raise SchemaValidationError(f"{field_name} must be a boolean")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate a sequence of strings and store it as a tuple."""

    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a list of strings")
    return tuple(_required_text(item, field_name) for item in value)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Validate a mapping and copy it into a plain dict."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be an object")
    return dict(value)


def _optional_mapping(value: Any, field_name: str) -> dict[str, Any] | None:
    """Validate an optional mapping."""

    if value is None:
        return None
    return _mapping(value, field_name)


def _mapping_tuple(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    """Validate a sequence of mapping payloads."""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a list of objects")
    return tuple(_mapping(item, field_name) for item in value)


def _validate_choice(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    """Validate an enum-like string against an allowed value set."""

    normalized = _required_text(value, field_name)
    if normalized not in allowed:
        allowed_values = ", ".join(allowed)
        raise SchemaValidationError(f"{field_name} must be one of: {allowed_values}")
    return normalized


def validate_clarification(
    needs_clarification: bool,
    clarifying_question: str | None,
) -> None:
    """Validate the shared worker clarification contract."""

    if not isinstance(needs_clarification, bool):
        raise SchemaValidationError("needs_clarification must be a boolean")
    if needs_clarification and not clarifying_question:
        raise SchemaValidationError(
            "clarifying_question is required when needs_clarification is true",
        )


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Latitude/longitude pair from request context."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not isinstance(self.latitude, (int, float)):
            raise SchemaValidationError("user_location.latitude must be numeric")
        if not isinstance(self.longitude, (int, float)):
            raise SchemaValidationError("user_location.longitude must be numeric")
        if self.latitude < -90 or self.latitude > 90:
            raise SchemaValidationError("user_location.latitude is out of range")
        if self.longitude < -180 or self.longitude > 180:
            raise SchemaValidationError("user_location.longitude is out of range")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GeoPoint":
        """Build a point from a request mapping."""

        return cls(
            latitude=float(_mapping_get(payload, "latitude")),
            longitude=float(_mapping_get(payload, "longitude")),
        )


@dataclass(frozen=True, slots=True)
class CitySelectInput:
    """Input contract produced by Intent Agent for City Select Agent."""

    country: str
    travel_month: int
    travel_year: int
    trip_type: str
    active_required_themes: tuple[str, ...]
    include_festivals: bool
    cleaned_raw_query: str = ""
    soft_preference_query: str = ""
    unsupported_conditions: tuple[str, ...] = ()
    destination_id: str | None = None
    user_location: GeoPoint | None = None
    execution_mode: str = "city_discovery"
    congestion_pref: str = "neutral"
    transport_pref: str = "unknown"
    theme_weights: Mapping[str, float] | None = None
    city_key: str | None = None
    ddb_pk: str | None = None
    destination_label: str | None = None
    preferred_theme_ids: tuple[str, ...] = ()
    disliked_theme_ids: tuple[str, ...] = ()
    preferred_city_ids: tuple[str, ...] = ()
    disliked_city_ids: tuple[str, ...] = ()
    preferred_region_ids: tuple[str, ...] = ()
    disliked_region_ids: tuple[str, ...] = ()
    preferred_region_spans: tuple[str, ...] = ()
    disliked_region_spans: tuple[str, ...] = ()
    unresolved_region_spans: tuple[str, ...] = ()
    preferred_region_names: tuple[str, ...] = ()
    disliked_region_names: tuple[str, ...] = ()
    needs_clarification: bool = False
    clarifying_question: str | None = None
    contradiction_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "country", _required_text(self.country, "country"))
        object.__setattr__(
            self,
            "travel_month",
            _month(self.travel_month, "travel_month"),
        )
        if _required_int(self.travel_year, "travel_year") < 1:
            raise SchemaValidationError("travel_year must be positive")
        object.__setattr__(self, "trip_type", _required_text(self.trip_type, "trip_type"))
        object.__setattr__(
            self,
            "active_required_themes",
            _string_tuple(self.active_required_themes, "active_required_themes"),
        )
        object.__setattr__(
            self,
            "include_festivals",
            _bool(self.include_festivals, "include_festivals"),
        )
        object.__setattr__(
            self,
            "cleaned_raw_query",
            _free_text(self.cleaned_raw_query, "cleaned_raw_query"),
        )
        object.__setattr__(
            self,
            "soft_preference_query",
            _free_text(self.soft_preference_query, "soft_preference_query"),
        )
        object.__setattr__(
            self,
            "unsupported_conditions",
            _string_tuple(self.unsupported_conditions, "unsupported_conditions"),
        )
        object.__setattr__(
            self,
            "destination_id",
            _optional_text(self.destination_id, "destination_id"),
        )
        object.__setattr__(
            self,
            "execution_mode",
            _validate_choice(self.execution_mode, EXECUTION_MODES, "execution_mode"),
        )

        object.__setattr__(
            self,
            "congestion_pref",
            _validate_choice(self.congestion_pref, ("quiet", "vibrant", "neutral"), "congestion_pref"),
        )
        object.__setattr__(
            self,
            "transport_pref",
            _validate_choice(self.transport_pref, ("walk", "car", "unknown"), "transport_pref"),
        )
        object.__setattr__(
            self,
            "theme_weights",
            _optional_mapping(self.theme_weights, "theme_weights"),
        )
        object.__setattr__(self, "city_key", _optional_text(self.city_key, "city_key"))
        object.__setattr__(self, "ddb_pk", _optional_text(self.ddb_pk, "ddb_pk"))
        object.__setattr__(
            self,
            "destination_label",
            _optional_text(self.destination_label, "destination_label"),
        )
        object.__setattr__(
            self,
            "preferred_theme_ids",
            _string_tuple(self.preferred_theme_ids, "preferred_theme_ids"),
        )
        object.__setattr__(
            self,
            "disliked_theme_ids",
            _string_tuple(self.disliked_theme_ids, "disliked_theme_ids"),
        )
        object.__setattr__(
            self,
            "preferred_city_ids",
            _string_tuple(self.preferred_city_ids, "preferred_city_ids"),
        )
        object.__setattr__(
            self,
            "disliked_city_ids",
            _string_tuple(self.disliked_city_ids, "disliked_city_ids"),
        )
        object.__setattr__(
            self,
            "preferred_region_ids",
            _string_tuple(self.preferred_region_ids, "preferred_region_ids"),
        )
        object.__setattr__(
            self,
            "disliked_region_ids",
            _string_tuple(self.disliked_region_ids, "disliked_region_ids"),
        )
        object.__setattr__(
            self,
            "preferred_region_spans",
            _string_tuple(self.preferred_region_spans, "preferred_region_spans"),
        )
        object.__setattr__(
            self,
            "disliked_region_spans",
            _string_tuple(self.disliked_region_spans, "disliked_region_spans"),
        )
        object.__setattr__(
            self,
            "unresolved_region_spans",
            _string_tuple(self.unresolved_region_spans, "unresolved_region_spans"),
        )
        object.__setattr__(
            self,
            "preferred_region_names",
            _string_tuple(self.preferred_region_names, "preferred_region_names"),
        )
        object.__setattr__(
            self,
            "disliked_region_names",
            _string_tuple(self.disliked_region_names, "disliked_region_names"),
        )
        object.__setattr__(
            self,
            "needs_clarification",
            _bool(self.needs_clarification, "needs_clarification"),
        )
        object.__setattr__(
            self,
            "clarifying_question",
            _optional_text(self.clarifying_question, "clarifying_question"),
        )
        object.__setattr__(
            self,
            "contradiction_reasons",
            _string_tuple(self.contradiction_reasons, "contradiction_reasons"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CitySelectInput":
        """Build from the current City Select input mapping."""

        user_location = _mapping_get(payload, "user_location", "userLocation", default=None)
        return cls(
            country=_mapping_get(payload, "country"),
            travel_month=_mapping_get(payload, "travel_month", "travelMonth"),
            travel_year=_mapping_get(payload, "travel_year", "travelYear"),
            trip_type=_mapping_get(payload, "trip_type", "tripType"),
            destination_id=_mapping_get(
                payload,
                "destination_id",
                "destinationId",
                default=None,
            ),
            active_required_themes=_mapping_get(payload, "active_required_themes"),
            cleaned_raw_query=_mapping_get(payload, "cleaned_raw_query", default=""),
            soft_preference_query=_mapping_get(
                payload,
                "soft_preference_query",
                default="",
            ),
            unsupported_conditions=_mapping_get(
                payload,
                "unsupported_conditions",
                default=(),
            ),
            user_location=(
                GeoPoint.from_mapping(user_location)
                if user_location is not None
                else None
            ),
            include_festivals=_mapping_get(
                payload,
                "include_festivals",
                "includeFestivals",
            ),
            execution_mode=_mapping_get(payload, "execution_mode", default="city_discovery"),

            congestion_pref=_mapping_get(payload, "congestion_pref", "congestionPref", default="neutral"),
            transport_pref=_mapping_get(payload, "transport_pref", "transportPref", default="unknown"),
            theme_weights=_mapping_get(payload, "theme_weights", "themeWeights", "request_theme_weights", "requestThemeWeights", default=None),
            city_key=_mapping_get(
                payload,
                "city_key",
                "cityKey",
                "destination_city_key",
                "destinationCityKey",
                default=None,
            ),
            ddb_pk=_mapping_get(payload, "ddb_pk", "ddbPk", default=None),
            destination_label=_mapping_get(
                payload,
                "destination_label",
                "destinationLabel",
                default=None,
            ),
            preferred_theme_ids=_mapping_get(payload, "preferred_theme_ids", default=()),
            disliked_theme_ids=_mapping_get(payload, "disliked_theme_ids", default=()),
            preferred_city_ids=_mapping_get(payload, "preferred_city_ids", default=()),
            disliked_city_ids=_mapping_get(payload, "disliked_city_ids", default=()),
            preferred_region_ids=_mapping_get(payload, "preferred_region_ids", default=()),
            disliked_region_ids=_mapping_get(payload, "disliked_region_ids", default=()),
            preferred_region_spans=_mapping_get(payload, "preferred_region_spans", default=()),
            disliked_region_spans=_mapping_get(payload, "disliked_region_spans", default=()),
            unresolved_region_spans=_mapping_get(
                payload,
                "unresolved_region_spans",
                default=(),
            ),
            preferred_region_names=_mapping_get(
                payload,
                "preferred_region_names",
                default=(),
            ),
            disliked_region_names=_mapping_get(
                payload,
                "disliked_region_names",
                default=(),
            ),
            needs_clarification=_mapping_get(
                payload,
                "needs_clarification",
                default=False,
            ),
            clarifying_question=_mapping_get(
                payload,
                "clarifying_question",
                default=None,
            ),
            contradiction_reasons=_mapping_get(
                payload,
                "contradiction_reasons",
                default=(),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SelectedCity:
    """Selected city summary from Candidate Evidence Agent."""

    city_id: str
    city_name_ko: str
    country: str
    selection_reason_code: tuple[str, ...] = ()
    ddb_pk: str | None = None
    province: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "city_id", _required_text(self.city_id, "city_id"))
        object.__setattr__(
            self,
            "city_name_ko",
            _required_text(self.city_name_ko, "city_name_ko"),
        )
        object.__setattr__(self, "country", _required_text(self.country, "country"))
        object.__setattr__(
            self,
            "selection_reason_code",
            _string_tuple(self.selection_reason_code, "selection_reason_code"),
        )
        object.__setattr__(self, "ddb_pk", _optional_text(self.ddb_pk, "ddb_pk"))
        object.__setattr__(self, "province", _optional_text(self.province, "province"))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SelectedCity":
        """Build a selected-city schema from a mapping."""

        return cls(
            city_id=_mapping_get(payload, "city_id", "destinationId"),
            city_name_ko=_mapping_get(payload, "city_name_ko", "city_name"),
            country=_mapping_get(payload, "country"),
            selection_reason_code=_mapping_get(
                payload,
                "selection_reason_code",
                default=(),
            ),
            ddb_pk=_mapping_get(payload, "ddb_pk", "ddbPk", default=None),
            province=_mapping_get(payload, "province", default=None),
        )


@dataclass(frozen=True, slots=True)
class CitySelectResult:
    """Internal package consumed by Planner Agent."""

    status: str
    failure_signals: tuple[str, ...] = ()
    needs_clarification: bool = False
    clarifying_question: str | None = None
    mode: str = "city_discovery"
    selected_city: SelectedCity | None = None
    city_anchor: dict[str, Any] | None = None
    city_rankings: tuple[dict[str, Any], ...] = ()
    recommended_places: tuple[dict[str, Any], ...] = ()
    reserve_places: tuple[dict[str, Any], ...] = ()
    festival_candidates: tuple[dict[str, Any], ...] = ()
    selected_festival_candidates: tuple[dict[str, Any], ...] = ()
    festival_seed_audit: dict[str, Any] = field(default_factory=dict)
    coverage_audit: dict[str, Any] = field(default_factory=dict)
    retrieval_audit: dict[str, Any] = field(default_factory=dict)
    candidate_counts: dict[str, Any] = field(default_factory=dict)
    warnings: dict[str, Any] = field(default_factory=dict)
    fallback_audit: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _validate_choice(self.status, CANDIDATE_EVIDENCE_STATUSES, "status"),
        )
        object.__setattr__(
            self,
            "failure_signals",
            _string_tuple(self.failure_signals, "failure_signals"),
        )
        object.__setattr__(
            self,
            "needs_clarification",
            _bool(self.needs_clarification, "needs_clarification"),
        )
        object.__setattr__(
            self,
            "clarifying_question",
            _optional_text(self.clarifying_question, "clarifying_question"),
        )
        validate_clarification(self.needs_clarification, self.clarifying_question)
        object.__setattr__(self, "mode", _validate_choice(self.mode, EXECUTION_MODES, "mode"))
        object.__setattr__(self, "city_anchor", _optional_mapping(self.city_anchor, "city_anchor"))
        object.__setattr__(self, "city_rankings", _mapping_tuple(self.city_rankings, "city_rankings"))
        object.__setattr__(
            self,
            "recommended_places",
            _mapping_tuple(self.recommended_places, "recommended_places"),
        )
        object.__setattr__(self, "reserve_places", _mapping_tuple(self.reserve_places, "reserve_places"))
        object.__setattr__(
            self,
            "festival_candidates",
            _mapping_tuple(self.festival_candidates, "festival_candidates"),
        )
        object.__setattr__(
            self,
            "selected_festival_candidates",
            _mapping_tuple(
                self.selected_festival_candidates,
                "selected_festival_candidates",
            ),
        )
    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CitySelectResult":
        selected_city = _mapping_get(payload, "selected_city", default=None)
        return cls(
            status=_mapping_get(payload, "status"),
            failure_signals=_mapping_get(payload, "failure_signals", default=()),
            needs_clarification=_mapping_get(
                payload,
                "needs_clarification",
                default=False,
            ),
            clarifying_question=_mapping_get(
                payload,
                "clarifying_question",
                default=None,
            ),
            mode=_mapping_get(payload, "mode", default="city_discovery"),
            selected_city=(
                SelectedCity.from_mapping(selected_city)
                if selected_city is not None
                else None
            ),
            city_anchor=_mapping_get(payload, "city_anchor", default=None),
            city_rankings=_mapping_get(payload, "city_rankings", default=()),
            recommended_places=_mapping_get(payload, "recommended_places", default=()),
            reserve_places=_mapping_get(payload, "reserve_places", default=()),
            festival_candidates=_mapping_get(payload, "festival_candidates", default=()),
            selected_festival_candidates=_mapping_get(
                payload,
                "selected_festival_candidates",
                default=(),
            ),
            festival_seed_audit=_mapping_get(payload, "festival_seed_audit", default={}),
            coverage_audit=_mapping_get(payload, "coverage_audit", default={}),
            retrieval_audit=_mapping_get(payload, "retrieval_audit", default={}),
            candidate_counts=_mapping_get(payload, "candidate_counts", default={}),
            warnings=_mapping_get(payload, "warnings", default={}),
            fallback_audit=_mapping_get(payload, "fallback_audit", default={}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class FestivalVerification:
    """Festival date verification payload consumed by Planner Agent."""

    festival_id: str
    name: str
    date_status: str
    start_date: str | None
    end_date: str | None
    is_applicable_to_trip: bool
    planner_policy: str
    source_type: str
    confidence: float
    evidence_summary: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "festival_id",
            _required_text(self.festival_id, "festival_id"),
        )
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(
            self,
            "date_status",
            _validate_choice(self.date_status, FESTIVAL_DATE_STATUSES, "date_status"),
        )
        object.__setattr__(self, "start_date", _optional_text(self.start_date, "start_date"))
        object.__setattr__(self, "end_date", _optional_text(self.end_date, "end_date"))
        object.__setattr__(
            self,
            "is_applicable_to_trip",
            _bool(self.is_applicable_to_trip, "is_applicable_to_trip"),
        )
        object.__setattr__(
            self,
            "planner_policy",
            _validate_choice(self.planner_policy, PLANNER_POLICIES, "planner_policy"),
        )
        object.__setattr__(
            self,
            "source_type",
            _required_text(self.source_type, "source_type"),
        )
        if not isinstance(self.confidence, (int, float)):
            raise SchemaValidationError("confidence must be numeric")
        if self.confidence < 0 or self.confidence > 1:
            raise SchemaValidationError("confidence must be between 0 and 1")
        object.__setattr__(
            self,
            "evidence_summary",
            _required_text(self.evidence_summary, "evidence_summary"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FestivalVerification":
        """Build from a Festival Verifier output mapping."""

        return cls(
            festival_id=_mapping_get(payload, "festival_id"),
            name=_mapping_get(payload, "name"),
            date_status=_mapping_get(payload, "date_status"),
            start_date=_mapping_get(payload, "start_date", default=None),
            end_date=_mapping_get(payload, "end_date", default=None),
            is_applicable_to_trip=_mapping_get(payload, "is_applicable_to_trip"),
            planner_policy=_mapping_get(payload, "planner_policy"),
            source_type=_mapping_get(payload, "source_type"),
            confidence=float(_mapping_get(payload, "confidence")),
            evidence_summary=_mapping_get(payload, "evidence_summary"),
        )


@dataclass(frozen=True, slots=True)
class ExplanationReasonRef:
    """Internal audit link between generated text and supporting evidence."""

    reason_id: str
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    reason_text: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_id", _required_text(self.reason_id, "reason_id"))
        object.__setattr__(
            self,
            "evidence_refs",
            _string_tuple(self.evidence_refs, "evidence_refs"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _string_tuple(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "reason_text",
            _optional_text(self.reason_text, "reason_text"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExplanationReasonRef":
        """Build an explanation audit reference from a mapping."""

        return cls(
            reason_id=_mapping_get(payload, "reason_id"),
            evidence_refs=_mapping_get(payload, "evidence_refs"),
            reason_codes=_mapping_get(payload, "reason_codes", default=()),
            reason_text=_mapping_get(payload, "reason_text", default=None),
        )


@dataclass(frozen=True, slots=True)
class PlannerExplanationAudit:
    """Internal Planner audit for user-facing explanation validation.

    This structure is not a public response field. Response Packager should use
    it only to validate/mask generated explanations and then keep it internal.
    """

    reason_refs: tuple[ExplanationReasonRef, ...] = ()
    itinerary_flow_refs: tuple[str, ...] = ()
    hidden_internal_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reason_refs = tuple(
            item
            if isinstance(item, ExplanationReasonRef)
            else ExplanationReasonRef.from_mapping(item)
            for item in self.reason_refs
        )
        object.__setattr__(self, "reason_refs", reason_refs)
        object.__setattr__(
            self,
            "itinerary_flow_refs",
            _string_tuple(self.itinerary_flow_refs, "itinerary_flow_refs"),
        )
        object.__setattr__(
            self,
            "hidden_internal_notes",
            _string_tuple(self.hidden_internal_notes, "hidden_internal_notes"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PlannerExplanationAudit":
        """Build Planner explanation audit details from a mapping."""

        return cls(
            reason_refs=tuple(
                ExplanationReasonRef.from_mapping(item)
                for item in _mapping_get(payload, "reason_refs", default=())
            ),
            itinerary_flow_refs=_mapping_get(payload, "itinerary_flow_refs", default=()),
            hidden_internal_notes=_mapping_get(
                payload,
                "hidden_internal_notes",
                default=(),
            ),
        )


@dataclass(frozen=True, slots=True)
class PlannerOutput:
    """Planner internal output before deterministic response packaging."""

    itinerary: tuple[dict[str, Any], ...]
    recommendation_reasons: tuple[str, ...]
    itinerary_flow_reason: str
    external_links: dict[str, Any]
    confidence: float
    user_notice: tuple[str, ...] = ()
    validation_result: dict[str, Any] = field(default_factory=dict)
    alternative_itinerary: tuple[dict[str, Any], ...] = ()
    explanation_audit: PlannerExplanationAudit | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "itinerary", _mapping_tuple(self.itinerary, "itinerary"))
        object.__setattr__(
            self,
            "alternative_itinerary",
            _mapping_tuple(self.alternative_itinerary, "alternative_itinerary"),
        )
        object.__setattr__(
            self,
            "recommendation_reasons",
            _string_tuple(self.recommendation_reasons, "recommendation_reasons"),
        )
        object.__setattr__(
            self,
            "itinerary_flow_reason",
            _required_text(self.itinerary_flow_reason, "itinerary_flow_reason"),
        )
        object.__setattr__(self, "external_links", _mapping(self.external_links, "external_links"))
        if not isinstance(self.confidence, (int, float)):
            raise SchemaValidationError("confidence must be numeric")
        if self.confidence < 0 or self.confidence > 1:
            raise SchemaValidationError("confidence must be between 0 and 1")
        object.__setattr__(self, "user_notice", _string_tuple(self.user_notice, "user_notice"))
        object.__setattr__(
            self,
            "validation_result",
            _mapping(self.validation_result, "validation_result"),
        )
        if self.explanation_audit is not None and not isinstance(
            self.explanation_audit,
            PlannerExplanationAudit,
        ):
            object.__setattr__(
                self,
                "explanation_audit",
                PlannerExplanationAudit.from_mapping(self.explanation_audit),
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PlannerOutput":
        """Build from a Planner internal output mapping."""

        return cls(
            itinerary=_mapping_get(payload, "itinerary"),
            alternative_itinerary=_mapping_get(
                payload,
                "alternative_itinerary",
                "alternativeItinerary",
                default=(),
            ),
            recommendation_reasons=_mapping_get(
                payload,
                "recommendation_reasons",
                "recommendationReasons",
            ),
            itinerary_flow_reason=_mapping_get(
                payload,
                "itinerary_flow_reason",
                "itineraryFlowReason",
            ),
            external_links=_mapping_get(payload, "external_links", "externalLinks"),
            confidence=float(_mapping_get(payload, "confidence")),
            user_notice=_mapping_get(payload, "user_notice", default=()),
            validation_result=_mapping_get(payload, "validation_result"),
            explanation_audit=(
                PlannerExplanationAudit.from_mapping(explanation_audit)
                if (
                    explanation_audit := _mapping_get(
                        payload,
                        "explanation_audit",
                        default=None,
                    )
                )
                is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkerOutputState:
    """Generic worker status wrapper for shared fallback validation."""

    status: str
    needs_clarification: bool = False
    clarifying_question: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.status, "status")
        object.__setattr__(
            self,
            "needs_clarification",
            _bool(self.needs_clarification, "needs_clarification"),
        )
        object.__setattr__(
            self,
            "clarifying_question",
            _optional_text(self.clarifying_question, "clarifying_question"),
        )
        validate_clarification(self.needs_clarification, self.clarifying_question)


@dataclass(frozen=True, slots=True)
class CitySelectionResult:
    """Output contract produced by City Select Agent for Planner Agent."""

    selected_city: SelectedCity
    representative_seed: dict[str, Any]
    score_breakdown: dict[str, float]
    retrieval_audit: dict[str, Any]
    alternative_city: dict[str, Any] | None = None
    selection_reason_code: tuple[str, ...] = ()
    seeds: tuple[dict[str, Any], ...] = ()
    headline_seed: str | None = None
    theme_evidence: tuple[dict[str, Any], ...] = ()
    missing_themes: tuple[str, ...] = ()
    passthrough: dict[str, Any] = field(default_factory=dict)
    theme_evidence_summary: dict[str, int] = field(default_factory=dict)
    planner_hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""

        return asdict(self)


__all__ = [
    "CANDIDATE_EVIDENCE_STATUSES",
    "EXECUTION_MODES",
    "FESTIVAL_DATE_STATUSES",
    "PLANNER_POLICIES",
    "SCHEMA_GROUPS",
    "CitySelectInput",
    "CitySelectionResult",
    "CitySelectResult",
    "ExplanationReasonRef",
    "FestivalVerification",
    "GeoPoint",
    "PlannerOutput",
    "PlannerExplanationAudit",
    "SchemaValidationError",
    "SelectedCity",
    "WorkerOutputState",
    "validate_clarification",
]
