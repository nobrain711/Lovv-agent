from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.steps.route_days.payloads import route_payload, selection_payload
from lovv_agent_v2.agents.planner.steps.route_days.place_selection import (
    PlannerSelectionInput,
    build_working_set,
)
from lovv_agent_v2.agents.planner.steps.route_days.routing import route_days
from lovv_agent_v2.common.telemetry_threading import submit_with_context
from lovv_agent_v2.tools.runtime_containers import PlannerRuntimeTools
from lovv_agent_v2.tools.travel_time_provider import TravelTimeProvider
from lovv_agent_v2.models.schemas import SchemaValidationError

PLANNER_RETRIEVAL_TOP_K = 50


@dataclass(frozen=True, slots=True)
class PlannerAgentRequest:
    selected_city: Mapping[str, object]
    city_id: str | None
    ddb_pk: str | None
    raw_query: str
    soft_query: str
    seeds: tuple[Mapping[str, object], ...]
    active_themes: tuple[str, ...]
    theme_weights: Mapping[str, float] | None
    trip_type: str
    transport_pref: str
    min_count: int
    target_count: int
    preferred_themes: tuple[str, ...] = ()
    raw_query_vector: tuple[float, ...] = ()
    fallback_raw_places: tuple[Mapping[str, object], ...] = ()
    fallback_soft_places: tuple[Mapping[str, object], ...] = ()
    festival_places: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerAgentTools:
    runtime: PlannerRuntimeTools | None
    travel_time_provider: TravelTimeProvider


@dataclass(frozen=True, slots=True)
class PlannerAgentResult:
    place_pool: dict[str, object]
    selection: dict[str, object]
    route: dict[str, object]


@dataclass(frozen=True, slots=True)
class PlannerAgent:
    tools: PlannerAgentTools

    def run(self, request: PlannerAgentRequest) -> PlannerAgentResult:
        place_pool = self.retrieve_places(request)
        selection, route = self.route_place_pool(request, place_pool)
        return PlannerAgentResult(place_pool=place_pool, selection=selection, route=route)

    def retrieve_places(self, request: PlannerAgentRequest) -> dict[str, object]:
        seed_places = _seed_places(request.seeds)
        runtime = self.tools.runtime
        if runtime is None:
            raw_places = (*seed_places, *request.fallback_raw_places, *request.festival_places)
            soft_places = request.fallback_soft_places
            return {
                "raw_places": raw_places,
                "soft_places": soft_places,
                "audit": _retrieve_audit(
                    request,
                    "city_select_scoring_audit_fallback",
                    raw_places,
                    soft_places,
                    festival_seed_count=len(request.festival_places),
                ),
            }

        raw_places, soft_places = _retrieve_raw_and_soft(
            request,
            runtime,
        )
        raw_places = (*seed_places, *raw_places, *request.festival_places)
        return {
            "raw_places": raw_places,
            "soft_places": soft_places,
            "audit": _retrieve_audit(
                request,
                "planner_city_anchored_vector_search",
                raw_places,
                soft_places,
                festival_seed_count=len(request.festival_places),
            ),
        }

    def route_place_pool(
        self,
        request: PlannerAgentRequest,
        place_pool: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        selection = build_working_set(
            PlannerSelectionInput(
                raw_places=_mapping_sequence(place_pool.get("raw_places")),
                soft_places=_mapping_sequence(place_pool.get("soft_places")),
                seeds=request.seeds,
                active_themes=request.active_themes,
                secondary_themes=request.preferred_themes,
                theme_weights=request.theme_weights,
                trip_type=request.trip_type,
                target_count=request.target_count,
                min_count=request.min_count,
            ),
        )
        provider = self.tools.travel_time_provider
        snapped = provider.snap_places(tuple(place.payload for place in selection.places), request.transport_pref)
        excluded_ids = set(snapped.excluded_place_ids)
        snapped_ids = {_required_text(place.get("place_id", place.get("placeId")), "place_id") for place in snapped.places}
        routable = tuple(
            place for place in selection.places if place.place_id in snapped_ids and place.place_id not in excluded_ids
        )
        routable_ids = {item.place_id for item in routable}
        unroutable = tuple(place for place in selection.places if place.place_id not in routable_ids)
        matrix = provider.matrix_minutes(tuple(place.place_id for place in routable), request.transport_pref)
        routed = route_days(
            routable,
            trip_type=request.trip_type,
            transport_pref=request.transport_pref,
            durations=matrix.durations,
            provider_audit={
                **dict(snapped.audit),
                **dict(matrix.audit),
                "unroutable_place_ids": tuple(place.place_id for place in unroutable),
            },
        )
        reserve = (*selection.reserve, *unroutable, *routed.reserve)
        return (
            selection_payload(
                selection,
                reserve,
                min_count=request.min_count,
                target_count=request.target_count,
                routable_count=len(routable),
            ),
            route_payload(routed, reserve),
        )


def _retrieve_raw_and_soft(
    request: PlannerAgentRequest,
    runtime: PlannerRuntimeTools,
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        raw_future = submit_with_context(executor, lambda: _raw_channel(request, runtime))
        soft_future = submit_with_context(executor, lambda: _soft_channel(request, runtime))
        return raw_future.result(), soft_future.result()


def _raw_channel(
    request: PlannerAgentRequest,
    runtime: PlannerRuntimeTools,
) -> tuple[Mapping[str, object], ...]:
    return _candidate_payloads(
        runtime.destination_search.search_candidates(
            _raw_query_vector(request, runtime),
            top_k=PLANNER_RETRIEVAL_TOP_K,
            city_id=request.city_id,
            ddb_pk=None,
            theme=None,
        ),
        similarity_key="raw_similarity",
    )


def _soft_channel(
    request: PlannerAgentRequest,
    runtime: PlannerRuntimeTools,
) -> tuple[Mapping[str, object], ...]:
    soft_query = _optional_text(request.soft_query)
    if not soft_query:
        return ()
    return _candidate_payloads(
            runtime.destination_search.search_candidates(
                runtime.embedding.embed_query(soft_query),
                top_k=PLANNER_RETRIEVAL_TOP_K,
                city_id=request.city_id,
                ddb_pk=None,
                theme=None,
        ),
        similarity_key="soft_similarity",
    )


def _raw_query_vector(
    request: PlannerAgentRequest,
    runtime: PlannerRuntimeTools,
) -> Sequence[float]:
    if request.raw_query_vector:
        return request.raw_query_vector
    return runtime.embedding.embed_query(
        _required_text(request.raw_query, "cleaned_raw_query"),
    )


def _candidate_payloads(
    candidates: Sequence[object],
    *,
    similarity_key: str,
) -> tuple[Mapping[str, object], ...]:
    payloads: list[Mapping[str, object]] = []
    for candidate in candidates:
        payload = _candidate_payload(candidate)
        distance = payload.get("distance")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            similarity = max(0.0, 1.0 - float(distance))
            payload = {
                **payload,
                similarity_key: similarity,
                "score_audit": {"score_components": {similarity_key: similarity}},
            }
        payloads.append(payload)
    return tuple(payloads)


def _candidate_payload(candidate: object) -> Mapping[str, object]:
    if isinstance(candidate, Mapping):
        return candidate
    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict) and isinstance(payload := to_dict(), Mapping):
        return _with_promoted_metadata(payload)
    raise SchemaValidationError("candidate must be a mapping or expose to_dict")


def _with_promoted_metadata(payload: Mapping[str, object]) -> Mapping[str, object]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return payload
    promoted = dict(payload)
    for key in ("indoor_outdoor", "attraction_subtype_code", "attraction_subtype_name"):
        if key in metadata and key not in promoted:
            promoted[key] = metadata[key]
    return promoted


def _seed_places(seeds: Sequence[Mapping[str, object]]) -> tuple[Mapping[str, object], ...]:
    return tuple(payload for seed in seeds if (payload := _seed_place(seed)) is not None)


def _seed_place(seed: Mapping[str, object]) -> Mapping[str, object] | None:
    if (place_id := _optional_text(seed.get("place_id", seed.get("placeId")))) is None:
        return None
    if (title := _optional_text(seed.get("title"))) is None:
        return None
    theme = _optional_text(seed.get("theme"))
    if not (theme_tags := _theme_tags(seed, theme)):
        return None
    raw_similarity = _optional_number(seed.get("sim", seed.get("raw_similarity"))) or 1.0
    return {
        **dict(seed),
        "place_id": place_id,
        "title": title,
        "theme_tags": theme_tags,
        "assigned_theme": _optional_text(seed.get("assigned_theme")) or theme_tags[0],
        "score_audit": {"score_components": {"raw_similarity": raw_similarity}},
        "soft_similarity": _optional_number(seed.get("soft_similarity")) or raw_similarity,
    }


def _theme_tags(seed: Mapping[str, object], theme: str | None) -> tuple[str, ...]:
    value = seed.get("theme_tags", seed.get("themeTags"))
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return (theme,) if theme is not None else ()


def _retrieve_audit(
    request: PlannerAgentRequest,
    source: str,
    raw_places: Sequence[Mapping[str, object]],
    soft_places: Sequence[Mapping[str, object]],
    *,
    festival_seed_count: int,
) -> dict[str, object]:
    return {
        "retrieve_source": source,
        "city_id": request.city_id,
        "ddb_pk": request.ddb_pk,
        "raw_channel_theme": None,
        "soft_channel_theme": None,
        "preferred_theme_channels": [],
        "raw_count": len(raw_places),
        "soft_count": len(soft_places),
        "festival_seed_count": festival_seed_count,
    }


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    return () if not isinstance(value, (list, tuple)) else tuple(
        _mapping(item, "mapping sequence item") for item in value
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_number(value: object) -> float | None:
    return None if isinstance(value, bool) or not isinstance(value, (int, float)) else float(value)
