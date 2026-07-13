from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace, coerce_place, selection_sort_key
from lovv_agent_v2.agents.planner.state.context import candidate_payloads, planner_city_input, runtime_tools
from lovv_agent_v2.agents.planner.steps.apply_edit.residual_query import residual_discovery_query
from lovv_agent_v2.agents.planner.steps.apply_edit.result_day_regenerate import (
    day_regenerate_update,
)
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import DurationLookup, max_leg_min
from lovv_agent_v2.agents.planner.steps.route_days.trim_policy import MAX_HARD_LEG_MIN
from lovv_agent_v2.agents.planner.steps.apply_edit.result import failed_update


def apply_day_regenerate(
    state: Mapping[str, Any],
    modify_intent: Mapping[str, Any],
) -> dict[str, Any]:
    request = _mapping(modify_intent.get("day_regenerate"))
    day = _int(request.get("day"))
    full_order = tuple(current_order(_request(state), state))
    order = tuple(item for item in full_order if _int(item.get("day")) == day)
    if day <= 0 or not order:
        return failed_update(state, _failed_edit("day_regenerate_target_unresolved", day=day))
    condition = _mapping(request.get("condition"))
    candidates = _candidates(state, condition, day, len(order))
    selected = _selection(candidates, len(order))
    if len(selected) < len(order):
        reason = "day_regenerate_no_candidate" if not candidates else "day_regenerate_route_infeasible"
        return failed_update(
            state,
            _failed_edit(reason, day=day, tried_candidate_count=len(candidates), requested_slot_count=len(order)),
        )
    return day_regenerate_update(state, day, order, selected, full_order=full_order)


def _candidates(
    state: Mapping[str, Any],
    condition: Mapping[str, Any],
    day: int,
    target_count: int,
) -> tuple[PlannerPlace, ...]:
    query = _optional_text(condition.get("replacement_query"))
    payloads = _retrieved_candidates(state, query) if query else _reserve_pool(state)
    excluded = _excluded_ids(state, condition, day)
    candidates = _coerced_candidates(payloads, excluded, state)
    if query is None and len(candidates) < target_count:
        backfill_payloads = _retrieved_candidates(state, residual_discovery_query(state))
        candidates = (*candidates, *_coerced_candidates(backfill_payloads, excluded, state, candidates))
    themes = _preferred_themes(state, condition)
    sorted_candidates = sorted(candidates, key=selection_sort_key, reverse=True)
    if not themes:
        return tuple(sorted_candidates)
    preferred = [place for place in sorted_candidates if _matches_any_theme(place, themes)]
    others = [place for place in sorted_candidates if not _matches_any_theme(place, themes)]
    return tuple((*preferred, *others))


def _coerced_candidates(
    payloads: Sequence[Mapping[str, Any]],
    excluded: set[str],
    state: Mapping[str, Any],
    existing: Sequence[PlannerPlace] = (),
) -> tuple[PlannerPlace, ...]:
    seen = {place.place_id for place in existing}
    candidates: list[PlannerPlace] = []
    for candidate in payloads:
        candidate_id = _candidate_id(candidate)
        if candidate_id in excluded or candidate_id in seen or not _same_destination(candidate, state):
            continue
        place = coerce_place(candidate)
        candidates.append(place)
        seen.add(place.place_id)
    return tuple(candidates)


def _retrieved_candidates(state: Mapping[str, Any], query: str | None) -> tuple[Mapping[str, Any], ...]:
    if query is None:
        return ()
    runtime = runtime_tools(state)
    if runtime is None:
        return ()
    return candidate_payloads(
        runtime.destination_search.search_candidates(
            runtime.embedding.embed_query(query),
            top_k=50,
            city_id=_destination_id(state),
            ddb_pk=None,
            theme=None,
        ),
        similarity_key="raw_similarity",
    )


def _selection(candidates: Sequence[PlannerPlace], count: int) -> tuple[PlannerPlace, ...]:
    selected: list[PlannerPlace] = []
    for candidate in candidates:
        trial = _ordered_by_medoid((*selected, candidate))
        if max_leg_min(trial, DurationLookup()) <= MAX_HARD_LEG_MIN:
            selected = list(trial)
        if len(selected) == count:
            break
    return tuple(selected)


def _ordered_by_medoid(places: Sequence[PlannerPlace]) -> tuple[PlannerPlace, ...]:
    if len(places) <= 1:
        return tuple(places)
    seed = min(places, key=lambda place: sum(_distance(place, other) for other in places))
    ordered = [replace(seed, is_seed=True)]
    remaining = [place for place in places if place.place_id != seed.place_id]
    while remaining:
        last = ordered[-1]
        next_place = min(remaining, key=lambda place: (round(_distance(last, place), 6), place.place_id))
        ordered.append(replace(next_place, is_seed=False))
        remaining = [place for place in remaining if place.place_id != next_place.place_id]
    return tuple(ordered)


def _reserve_pool(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    context = _mapping(_mapping(state.get("planner")).get("modify_context"))
    value = context.get("reserve_pool")
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _excluded_ids(state: Mapping[str, Any], condition: Mapping[str, Any], day: int) -> set[str]:
    excluded = {_candidate_id(item) for item in current_order(_request(state), state)}
    excluded.update(str(item) for item in condition.get("avoid_content_ids", ()) if isinstance(item, str))
    history = _mapping(_mapping(state.get("memory")).get("modify_history"))
    excluded.update(str(item) for item in history.get("replaced_content_ids", ()) if isinstance(item, str))
    return {item for item in excluded if item}


def _preferred_themes(state: Mapping[str, Any], condition: Mapping[str, Any]) -> tuple[str, ...]:
    explicit_theme = _optional_text(condition.get("theme"))
    if explicit_theme is not None:
        return (explicit_theme,)
    if _optional_text(condition.get("replacement_query")) is not None:
        return ()
    return tuple(
        theme
        for theme in planner_city_input(state).get("active_required_themes", ())
        if isinstance(theme, str) and theme.strip()
    )


def _matches_any_theme(place: PlannerPlace, themes: Sequence[str]) -> bool:
    return any(theme in place.theme_tags for theme in themes)


def _same_destination(candidate: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    destination_id = _destination_id(state)
    city_id = _optional_text(candidate.get("city_id", candidate.get("cityId")))
    return city_id is None or destination_id is None or city_id == destination_id


def _destination_id(state: Mapping[str, Any]) -> str | None:
    request = _request(state)
    modify = _mapping(_mapping(state.get("intent")).get("modify_intent"))
    city_input = planner_city_input(state)
    for value in (
        request.get("destinationId", request.get("destination_id")),
        modify.get("destination_id"),
        city_input.get("destination_id"),
    ):
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _failed_edit(reason_code: str, **fields: Any) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "suggested_theme_expansion_options": ("broaden_theme", "active_themes_only"),
        **fields,
    }


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("contentId", candidate.get("content_id", candidate.get("place_id", candidate.get("placeId"))))
    return value.strip() if isinstance(value, str) else ""


def _request(state: Mapping[str, Any]) -> Mapping[str, Any]:
    request = state.get("request")
    return request if isinstance(request, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _distance(first: PlannerPlace, second: PlannerPlace) -> float:
    if first.latitude is None or first.longitude is None:
        return 0.0
    if second.latitude is None or second.longitude is None:
        return 0.0
    return abs(first.latitude - second.latitude) + abs(first.longitude - second.longitude)
