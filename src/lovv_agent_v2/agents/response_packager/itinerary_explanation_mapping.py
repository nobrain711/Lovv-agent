from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.tools.city_select_contracts import AttractionCandidate
from lovv_agent_v2.models.schemas import PlannerExplanationAudit

INTERNAL_CLAIM_TERMS = (
    "top k",
    "top_k",
    "topk",
    "점수",
    "스코어",
    "ranking formula",
    "raw retrieval",
    "seed",
    "cluster",
    "relevance",
    "클러스터",
    "관련도",
    "score audit",
    "dynamodb",
    "s3 vector",
)


@dataclass(frozen=True, slots=True)
class CandidatePackageInput:
    selected_city: Mapping[str, object]
    query: Mapping[str, object]
    itinerary: Sequence[Mapping[str, Any]]
    validation_result: Mapping[str, object]


def enrich_itinerary(
    itinerary: Sequence[Mapping[str, Any]],
    dynamo_lookup: Any | None,
) -> tuple[tuple[dict[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    if dynamo_lookup is None:
        return tuple(dict(item) for item in itinerary), ()
    candidates = tuple(_candidate_from_item(index, item) for index, item in enumerate(itinerary))
    result = dynamo_lookup.enrich_final_places(candidates)
    enriched_by_id = {place.place_id: place for place in result.places}
    enriched_items = tuple(
        _with_enriched_details(item, enriched_by_id.get(_item_place_id(item)))
        for item in itinerary
    )
    warnings = tuple(warning.to_dict() if hasattr(warning, "to_dict") else dict(warning) for warning in result.warnings)
    return enriched_items, warnings


def build_safe_summary(package_input: CandidatePackageInput) -> dict[str, Any]:
    selected_city = package_input.selected_city
    query = package_input.query
    return {
        "selected_city": {
            "city_id": _text(selected_city.get("city_id", selected_city.get("destinationId")), "selected_city"),
            "city_name_ko": _text(selected_city.get("city_name_ko", selected_city.get("name")), "선택 도시"),
            "country": _text(selected_city.get("country"), "KR"),
            "selection_reason_code": list(_string_tuple(selected_city.get("selection_reason_code"))),
        },
        "query": {
            "cleaned_raw_query": _text(query.get("cleaned_raw_query"), ""),
            "soft_preference_query": _text(query.get("soft_preference_query"), ""),
        },
        "final_itinerary_items": [
            _item_prompt_summary(index, item) for index, item in enumerate(package_input.itinerary)
        ],
        "candidate_reason_claims": _reason_claims(package_input.itinerary),
        "verified_festivals": [
            _festival_prompt_summary(item)
            for item in package_input.itinerary
            if item.get("item_type") == "festival"
        ],
        "validation_result": _validation_prompt_summary(package_input.validation_result),
        "copy_rules": {
            "do_not_create_new_places": True,
            "do_not_create_named_restaurants": True,
            "do_not_expose_internal_scores": True,
        },
    }


def fallback_audit(itinerary: Sequence[Mapping[str, Any]]) -> PlannerExplanationAudit:
    refs = tuple(f"place:{_item_place_id(item)}" for item in itinerary)
    return PlannerExplanationAudit(
        itinerary_flow_refs=refs,
        hidden_internal_notes=("planner_copy_generation:v2_adapter",),
    )


def _candidate_from_item(index: int, item: Mapping[str, Any]) -> AttractionCandidate:
    return AttractionCandidate(
        key=_text(item.get("key"), f"item:{index}"),
        place_id=_item_place_id(item),
        distance=0.0,
        entity_type=_text(item.get("item_type"), "attraction"),
        city_id=_text(item.get("city_id"), ""),
        city_name_ko=_optional_text(item.get("city_name_ko")),
        title=_text(item.get("title"), "장소"),
        theme_tags=_string_tuple(item.get("theme_tags")),
        latitude=_optional_float(item.get("latitude")),
        longitude=_optional_float(item.get("longitude")),
        ddb_pk=_optional_text(item.get("ddb_pk")),
        ddb_sk=_optional_text(item.get("ddb_sk")),
        metadata={},
        details=_optional_mapping(item.get("details")),
    )


def _with_enriched_details(
    item: Mapping[str, Any],
    candidate: AttractionCandidate | None,
) -> dict[str, Any]:
    copied = dict(item)
    if candidate is not None:
        copied["details"] = candidate.details
    return copied


def _item_prompt_summary(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
    details = item.get("details")
    overview = None
    if isinstance(details, Mapping):
        overview = details.get("overview") or details.get("overview_ko")
    return {
        "item_ref": f"item:{index}",
        "item_type": item.get("item_type"),
        "placeId": item.get("placeId"),
        "festivalId": item.get("festivalId"),
        "title": item.get("title"),
        "city_id": item.get("city_id"),
        "city_name_ko": item.get("city_name_ko"),
        "theme_tags": list(_string_tuple(item.get("theme_tags"))),
        "source": item.get("source"),
        "overview": overview,
        "date_status": item.get("date_status"),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
    }


def _festival_prompt_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "festivalId": item.get("festivalId"),
        "title": item.get("title"),
        "date_status": item.get("date_status"),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "source": item.get("source"),
    }


def _validation_prompt_summary(validation_result: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": validation_result.get("status"),
        "festival_placed_count": validation_result.get("festival_placed_count"),
        "festival_skipped_count": validation_result.get("festival_skipped_count"),
        "planner_status_gate": validation_result.get("planner_status_gate"),
    }


def _reason_claims(itinerary: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, item in enumerate(itinerary):
        reason = _optional_text(item.get("reason"))
        if reason is None or _contains_internal_term(reason):
            continue
        place_id = _item_place_id(item)
        reason_code = _text(item.get("reason_code"), "place_pool")
        claims.append(
            {
                "claim_id": f"v2-itinerary-item-{index}",
                "scope": "place_pool",
                "text_ko": reason,
                "evidence_refs": [f"place:{place_id}", f"reason_code:{reason_code}"],
                "required_place_ids": [place_id],
                "public_eligible": True,
            },
        )
    return claims


def _item_place_id(item: Mapping[str, Any]) -> str:
    return _text(item.get("placeId", item.get("place_id")), "place")


def _contains_internal_term(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in INTERNAL_CLAIM_TERMS)


def _text(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = _optional_text(value)
        return () if normalized is None else (normalized,)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _optional_mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
