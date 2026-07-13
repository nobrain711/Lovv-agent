from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.planner.domain.place_model import (
    PlannerPlace,
    coerce_place,
    selection_sort_key,
)
from lovv_agent_v2.agents.planner.state.context import candidate_payloads, planner_city_input, runtime_tools
from lovv_agent_v2.agents.planner.steps.apply_edit.residual_query import residual_discovery_query


def candidate_pool(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[PlannerPlace, ...]:
    condition = _mapping(operation.get("condition"))
    query = _optional_text(condition.get("replacement_query"))
    payloads = _candidate_payloads(state, operation, target, query)
    excluded = _excluded_ids(state, target, condition)
    candidates = _coerced_candidates(payloads, excluded, state, operation, target)
    policy = _mapping(operation.get("seed_policy"))
    if policy.get("policy") == "same_theme_required":
        required = _optional_text(policy.get("required_theme")) or _optional_text(target.get("theme"))
        if required is not None:
            candidates = tuple(place for place in candidates if required in place.theme_tags)
    themes = _preferred_themes(state, condition, target)
    sorted_candidates = sorted(candidates, key=selection_sort_key, reverse=True)
    if not themes:
        return tuple(sorted_candidates)
    preferred = [place for place in sorted_candidates if _matches_any_theme(place, themes)]
    others = [place for place in sorted_candidates if not _matches_any_theme(place, themes)]
    return tuple((*preferred, *others))


def destination_id(state: Mapping[str, Any], target: Mapping[str, Any]) -> str | None:
    request = _request(state)
    modify = _modify_intent(state)
    city_input = planner_city_input(state)
    for value in (
        request.get("destinationId", request.get("destination_id")),
        modify.get("destination_id"),
        city_input.get("destination_id"),
        target.get("cityId", target.get("city_id")),
    ):
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _candidate_payloads(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
    query: str | None,
) -> tuple[Mapping[str, Any], ...]:
    if query is not None:
        return _retrieved_candidates(state, operation, target, query)
    reserve = _reserve_pool(state)
    return (*reserve, *_retrieved_candidates(state, operation, target, residual_discovery_query(state)))


def _coerced_candidates(
    payloads: Sequence[Mapping[str, Any]],
    excluded: set[str],
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[PlannerPlace, ...]:
    seen: set[str] = set()
    candidates: list[PlannerPlace] = []
    for candidate in payloads:
        candidate_id = _candidate_id(candidate)
        if candidate_id in excluded or candidate_id in seen or not _same_destination(candidate, state, target):
            continue
        place = _seed_adjusted(coerce_place(candidate), operation, target)
        candidates.append(place)
        seen.add(place.place_id)
    return tuple(candidates)


def _retrieved_candidates(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
    query: str,
) -> tuple[Mapping[str, Any], ...]:
    runtime = runtime_tools(state)
    if runtime is None:
        return ()
    return candidate_payloads(
        runtime.destination_search.search_candidates(
            runtime.embedding.embed_query(query),
            top_k=50,
            city_id=destination_id(state, target),
            ddb_pk=None,
            theme=None,
        ),
        similarity_key="raw_similarity",
    )


def _reserve_pool(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    context = _mapping(_mapping(state.get("planner")).get("modify_context"))
    value = context.get("reserve_pool")
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _excluded_ids(
    state: Mapping[str, Any],
    target: Mapping[str, Any],
    condition: Mapping[str, Any],
) -> set[str]:
    excluded = {_candidate_id(item) for item in current_order(_request(state), state)}
    excluded.update(str(item) for item in condition.get("avoid_content_ids", ()) if isinstance(item, str))
    history = _mapping(_mapping(state.get("memory")).get("modify_history"))
    excluded.update(str(item) for item in history.get("replaced_content_ids", ()) if isinstance(item, str))
    target_id = _optional_text(target.get("contentId", target.get("content_id")))
    if target_id is not None:
        excluded.add(target_id)
    return {item for item in excluded if item}


def _seed_adjusted(place: PlannerPlace, operation: Mapping[str, Any], target: Mapping[str, Any]) -> PlannerPlace:
    policy = _mapping(operation.get("seed_policy"))
    if policy.get("policy") != "same_theme_required":
        return place
    required = _optional_text(policy.get("required_theme")) or _optional_text(target.get("theme"))
    if required is None or required in place.theme_tags:
        return replace(place, is_seed=True)
    return place


def _preferred_themes(
    state: Mapping[str, Any],
    condition: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[str, ...]:
    explicit_theme = _optional_text(condition.get("theme"))
    if explicit_theme is not None:
        return (explicit_theme,)
    if _optional_text(condition.get("replacement_query")) is not None:
        return ()
    active_themes = tuple(
        theme
        for theme in planner_city_input(state).get("active_required_themes", ())
        if isinstance(theme, str) and theme.strip()
    )
    if active_themes:
        return active_themes
    target_theme = _optional_text(target.get("theme"))
    return (target_theme,) if target_theme is not None else ()


def _matches_any_theme(place: PlannerPlace, themes: Sequence[str]) -> bool:
    return any(theme in place.theme_tags for theme in themes)


def _same_destination(candidate: Mapping[str, Any], state: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    city_id = _optional_text(candidate.get("city_id", candidate.get("cityId")))
    selected_destination = destination_id(state, target)
    return city_id is None or selected_destination is None or city_id == selected_destination


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("contentId", candidate.get("content_id", candidate.get("place_id", candidate.get("placeId"))))
    return value.strip() if isinstance(value, str) else ""


def _request(state: Mapping[str, Any]) -> Mapping[str, Any]:
    request = state.get("request")
    return request if isinstance(request, Mapping) else {}


def _modify_intent(state: Mapping[str, Any]) -> Mapping[str, Any]:
    intent = _mapping(state.get("intent"))
    modify = intent.get("modify_intent")
    return modify if isinstance(modify, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
