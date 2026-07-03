from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from lovv_agent_v2.agents.response_packager.itinerary_item_payload import (
    build_itinerary_item_payload,
)
from lovv_agent_v2.agents.response_packager.notice import joined_notice, unsupported_notice
from lovv_agent_v2.models.clarification import Clarification
from lovv_agent_v2.models.schemas import (
    FestivalVerification,
    PlannerOutput,
    SchemaValidationError,
    SelectedCity,
)

DEFAULT_TTL_MINUTES = 30


def package_recommendation_response(
    *,
    planner_output: PlannerOutput | Mapping[str, Any] | None,
    request: Mapping[str, Any],
    selected_city: SelectedCity | Mapping[str, Any] | None,
    festival_verifications: Sequence[Any] = (),
    unsupported_conditions: Sequence[str] = (),
    recommendation_id: str | None = None,
    expires_at: str | None = None,
    notice: str | None = None,
    response_status: str = "modification_pending",
    clarification: Clarification | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request_payload = _request_payload(request)
    planner = _planner(planner_output)
    city = _selected_city(selected_city)
    internal_clarification = _clarification(clarification)
    generated_notice = unsupported_notice(unsupported_conditions)
    user_notice = (
        internal_clarification.prompt
        if response_status == "END_WAIT_USER" and internal_clarification is not None
        else notice or generated_notice
    )
    response = {
        "recommendationId": recommendation_id or request_payload["request_id"],
        "expiresAt": expires_at or _default_expires_at(),
        "destination": _destination_payload(city, request_payload, planner),
        "itinerary": _itinerary_payload(planner, request_payload),
        "explainability": _explainability_payload(
            planner,
            request_payload,
            unsupported_conditions=unsupported_conditions,
            notice=user_notice,
        ),
        "festivalDateVerifications": _festival_date_verification_payloads(
            festival_verifications,
        ),
        "links": _links_payload(planner),
    }
    if internal_clarification is not None:
        response["clarification"] = internal_clarification.to_public_dict()
    if response_status == "END_WAIT_USER" and internal_clarification is None:
        raise SchemaValidationError("END_WAIT_USER response requires clarification")
    return response


def _destination_payload(
    selected_city: SelectedCity | None,
    request: Mapping[str, Any],
    planner: PlannerOutput | None,
) -> dict[str, Any]:
    if selected_city is None:
        return {
            "destinationId": request.get("destination_id"),
            "name": _planner_city_name(planner, request.get("destination_id")),
            "country": request["country"],
            "region": None,
        }
    return {
        "destinationId": selected_city.city_id,
        "name": selected_city.city_name_ko,
        "country": selected_city.country,
        "region": None,
    }


def _planner_city_name(planner: PlannerOutput | None, destination_id: Any) -> str | None:
    if planner is None:
        return None
    for item in planner.itinerary:
        if destination_id is not None and item.get("city_id") != destination_id:
            continue
        value = item.get("city_name_ko")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _itinerary_payload(
    planner: PlannerOutput | None,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if planner is None:
        return {"tripType": request["trip_type"], "days": []}
    days: dict[int, list[dict[str, Any]]] = {}
    for sort_order, item in enumerate(planner.itinerary, start=1):
        day = int(item.get("day", 1) or 1)
        day_items = days.setdefault(day, [])
        item_with_order = {**item, "order": len(day_items) + 1}
        day_items.append(build_itinerary_item_payload(item_with_order, sort_order))
    return {
        "tripType": request["trip_type"],
        "days": [
            {"day": day, "items": items}
            for day, items in sorted(days.items(), key=lambda pair: pair[0])
        ],
    }


def _explainability_payload(
    planner: PlannerOutput | None,
    request: Mapping[str, Any],
    *,
    unsupported_conditions: Sequence[str],
    notice: str | None,
) -> dict[str, Any]:
    if planner is None:
        return {
            "matchedConditions": _matched_conditions(request),
            "unsupportedConditions": tuple(str(item) for item in unsupported_conditions),
            "recommendationReasons": (),
            "itineraryFlowReason": "",
            "confidence": 0.0,
            "userNotice": notice or "",
        }
    return {
        "matchedConditions": _matched_conditions(request),
        "unsupportedConditions": tuple(str(item) for item in unsupported_conditions),
        "recommendationReasons": planner.recommendation_reasons,
        "itineraryFlowReason": planner.itinerary_flow_reason,
        "confidence": planner.confidence,
        "userNotice": joined_notice(planner.user_notice, unsupported_conditions),
    }


def _festival_date_verification_payloads(
    festival_verifications: Sequence[Any],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "festivalId": verification.festival_id,
            "dateStatus": verification.date_status,
            "startDate": verification.start_date,
            "endDate": verification.end_date,
            "sourceUrl": None,
            "confidence": verification.confidence,
        }
        for verification in _festival_verification_tuple(festival_verifications)
    )


def _links_payload(planner: PlannerOutput | None) -> dict[str, Any]:
    if planner is None:
        return {}
    links: dict[str, Any] = {}
    for key, value in planner.external_links.items():
        if isinstance(value, Mapping) and isinstance(value.get("url"), str):
            links[key] = value["url"]
        if isinstance(value, str):
            links[key] = value
    return links


def _matched_conditions(request: Mapping[str, Any]) -> tuple[str, ...]:
    themes = tuple(str(theme) for theme in request.get("themes", ()))
    return (*themes, f"travelMonth:{request['travel_month']}")


def _planner(planner_output: PlannerOutput | Mapping[str, Any] | None) -> PlannerOutput | None:
    if planner_output is None:
        return None
    if isinstance(planner_output, PlannerOutput):
        return planner_output
    if isinstance(planner_output, Mapping):
        return PlannerOutput.from_mapping(planner_output)
    raise SchemaValidationError("planner_output must be PlannerOutput, mapping, or None")


def _selected_city(
    selected_city: SelectedCity | Mapping[str, Any] | None,
) -> SelectedCity | None:
    if selected_city is None:
        return None
    if isinstance(selected_city, SelectedCity):
        return selected_city
    if isinstance(selected_city, Mapping):
        return SelectedCity.from_mapping(selected_city)
    raise SchemaValidationError("selected_city must be SelectedCity, mapping, or None")


def _clarification(
    clarification: Clarification | Mapping[str, Any] | None,
) -> Clarification | None:
    if clarification is None:
        return None
    if isinstance(clarification, Clarification):
        return clarification
    if isinstance(clarification, Mapping):
        return Clarification.from_mapping(clarification)
    raise SchemaValidationError("clarification must be a Clarification")


def _festival_verification_tuple(
    festival_verifications: Sequence[Any],
) -> tuple[FestivalVerification, ...]:
    if isinstance(festival_verifications, (str, bytes)) or not isinstance(
        festival_verifications,
        Sequence,
    ):
        raise SchemaValidationError("festival_verifications must be a sequence")
    return tuple(
        item
        if isinstance(item, FestivalVerification)
        else FestivalVerification.from_mapping(_mapping(item, "festival_verification"))
        for item in festival_verifications
    )


def _request_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": _first_optional(
            request,
            "request_id",
            "requestId",
            "thread_id",
            "threadId",
        )
        or "mock-v2-request",
        "country": _first_optional(request, "country") or "KR",
        "travel_month": _first_optional(request, "travel_month", "travelMonth"),
        "trip_type": _first_optional(request, "trip_type", "tripType") or "modify",
        "destination_id": request.get("destination_id", request.get("destinationId")),
        "themes": tuple(request.get("themes", ())),
    }


def _first_optional(mapping: Mapping[str, Any], *keys: str) -> Any:
    return next((mapping[key] for key in keys if key in mapping), None)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


def _default_expires_at() -> str:
    return (datetime.now(UTC) + timedelta(minutes=DEFAULT_TTL_MINUTES)).replace(
        microsecond=0,
    ).isoformat().replace("+00:00", "Z")


__all__ = ["DEFAULT_TTL_MINUTES", "package_recommendation_response"]
