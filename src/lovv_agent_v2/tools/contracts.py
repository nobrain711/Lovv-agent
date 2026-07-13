"""Gateway-ready request/response contracts for ``lovv_agent_v2.tools``.

These DTOs exist so a future AgentCore Gateway adapter can reuse the same
request/response shape that today's in-process tool callers use, without
having to re-derive the payload contract from agent internals later. Every
field is JSON-serializable: ``dict``, ``list``, ``str``, ``int``, ``float``,
``bool``, or ``None``.

Hard constraints (see docs/specs/v2/LOVV_V2_TOOL_CODE_CONSOLIDATION_SPEC.md
section 3.2):

- This module MUST NOT import from ``agents.*``, ``core.*``, or
  ``infra.aws_clients``.
- This module MUST NOT reference the AWS SDK client library, the graph
  orchestration framework, the unified graph state type, that framework's
  graph-builder type, or the low-level AWS client-factory abstraction.
- No live client, SQL, or graph-framework state object may be stored on a
  DTO.

These contracts are additive scaffolding only. Nothing in
``lovv_agent_v2.tools`` wires them into the live query path today -
``DestinationSearchTool`` and ``RdsSavedItinerarySignalsTool`` keep returning
the same plain dict/tuple payloads they always have. A future
``app/LovvGatewayV2`` adapter would parse an event into one of these
requests, call the existing tool implementation, and normalize the result
back through the matching response DTO.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class ContractValidationError(ValueError):
    """Raised when a ``tools.contracts`` DTO is built from an invalid mapping."""


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} is required and must be a non-empty str")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a str or None")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an int or None")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    resolved = _optional_int(value, field_name)
    if resolved is not None and resolved <= 0:
        raise ContractValidationError(f"{field_name} must be a positive int")
    return resolved


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{field_name} must be a positive int")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field_name} must be a non-negative int")
    return value


def _tuple_of_str(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence of str")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ContractValidationError(f"{field_name} entries must be str")
        result.append(item)
    return tuple(result)


def _tuple_of_float(value: object, field_name: str) -> tuple[float, ...]:
    if value is None:
        raise ContractValidationError(f"{field_name} is required")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence of numbers")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ContractValidationError(f"{field_name} entries must be numbers")
        result.append(float(item))
    return tuple(result)


def _tuple_of_mapping(value: object, field_name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence of mappings")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ContractValidationError(f"{field_name} entries must be mappings")
        mapped: dict[str, Any] = {}
        for key, item_value in item.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{field_name} mapping keys must be strings")
            mapped[key] = item_value
        result.append(mapped)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DestinationSearchRequest:
    """JSON-serializable request payload for attraction destination search.

    Mirrors the keyword arguments accepted by
    ``tools.destination_search.DestinationSearchTool.search_candidates`` and
    ``tools.destination_search.build_attraction_search_request`` so a future
    Gateway adapter can parse an event directly into this shape.
    """

    query_vector: tuple[float, ...]
    city_id: str | None = None
    ddb_pk: str | None = None
    theme: str | None = None
    theme_tags: tuple[str, ...] = ()
    preferred_city_ids: tuple[str, ...] = ()
    disliked_city_ids: tuple[str, ...] = ()
    top_k: int | None = None

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> DestinationSearchRequest:
        return cls(
            query_vector=_tuple_of_float(m.get("query_vector"), "query_vector"),
            city_id=_optional_str(m.get("city_id"), "city_id"),
            ddb_pk=_optional_str(m.get("ddb_pk"), "ddb_pk"),
            theme=_optional_str(m.get("theme"), "theme"),
            theme_tags=_tuple_of_str(m.get("theme_tags"), "theme_tags"),
            preferred_city_ids=_tuple_of_str(m.get("preferred_city_ids"), "preferred_city_ids"),
            disliked_city_ids=_tuple_of_str(m.get("disliked_city_ids"), "disliked_city_ids"),
            top_k=_optional_positive_int(m.get("top_k"), "top_k"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_vector": list(self.query_vector),
            "city_id": self.city_id,
            "ddb_pk": self.ddb_pk,
            "theme": self.theme,
            "theme_tags": list(self.theme_tags),
            "preferred_city_ids": list(self.preferred_city_ids),
            "disliked_city_ids": list(self.disliked_city_ids),
            "top_k": self.top_k,
        }


@dataclass(frozen=True, slots=True)
class DestinationSearchResponse:
    """JSON-serializable response payload for attraction destination search.

    ``candidates`` holds plain mapping snapshots rather than the live
    ``AttractionCandidate`` dataclass so this contract never has to import
    agent-owned domain types.
    """

    candidates: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> DestinationSearchResponse:
        return cls(candidates=_tuple_of_mapping(m.get("candidates"), "candidates"))

    def to_dict(self) -> dict[str, Any]:
        return {"candidates": [dict(candidate) for candidate in self.candidates]}


@dataclass(frozen=True, slots=True)
class SavedItinerarySignalsRequest:
    """JSON-serializable request payload for the saved-itinerary signal read.

    Mirrors the keyword arguments accepted by
    ``tools.saved_itinerary_signals.RdsSavedItinerarySignalsTool.fetch_saved_itinerary_signals``.
    """

    actor_id: str
    thread_id: str
    recent_limit: int
    liked_limit: int

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> SavedItinerarySignalsRequest:
        return cls(
            actor_id=_required_str(m.get("actor_id"), "actor_id"),
            thread_id=_required_str(m.get("thread_id"), "thread_id"),
            recent_limit=_positive_int(m.get("recent_limit"), "recent_limit"),
            liked_limit=_positive_int(m.get("liked_limit"), "liked_limit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "thread_id": self.thread_id,
            "recent_limit": self.recent_limit,
            "liked_limit": self.liked_limit,
        }


@dataclass(frozen=True, slots=True)
class SavedItinerarySignalsResponse:
    """JSON-serializable response payload for the saved-itinerary signal read.

    Mirrors the dict shape returned today by
    ``RdsSavedItinerarySignalsTool.fetch_saved_itinerary_signals`` so a future
    Gateway adapter can validate/round-trip it without depending on the live
    tool implementation.
    """

    source: str
    saved_trip_count: int
    recent_itineraries: tuple[dict[str, Any], ...] = ()
    liked_itineraries: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any]) -> SavedItinerarySignalsResponse:
        return cls(
            source=_required_str(m.get("source"), "source"),
            saved_trip_count=_non_negative_int(m.get("saved_trip_count"), "saved_trip_count"),
            recent_itineraries=_tuple_of_mapping(m.get("recent_itineraries"), "recent_itineraries"),
            liked_itineraries=_tuple_of_mapping(m.get("liked_itineraries"), "liked_itineraries"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "saved_trip_count": self.saved_trip_count,
            "recent_itineraries": [dict(item) for item in self.recent_itineraries],
            "liked_itineraries": [dict(item) for item in self.liked_itineraries],
        }


__all__ = [
    "ContractValidationError",
    "DestinationSearchRequest",
    "DestinationSearchResponse",
    "SavedItinerarySignalsRequest",
    "SavedItinerarySignalsResponse",
]
