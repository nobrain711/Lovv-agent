from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import (
    PlannerPlace,
    coerce_place,
    merge_by_place_id,
    positive_int,
    seed_ids,
    selection_sort_key,
    theme_tuple,
    with_seed_flag,
    with_semantic_seed_source,
    with_soft_channel,
)
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import bounded_min_place_target
from lovv_agent_v2.agents.planner.steps.route_days.selection_policy import (
    ThemeSelectionInput,
    primary_theme,
    select_by_theme_quota,
    selected_theme_counts,
    theme_quota,
)
from lovv_agent_v2.agents.planner.steps.route_days.subtype_diversity import (
    SubtypeCapInput,
    apply_theme_subtype_cap,
    subtype_counts,
)

@dataclass(frozen=True, slots=True)
class PlannerSelectionInput:
    raw_places: Sequence[Mapping[str, object]]
    soft_places: Sequence[Mapping[str, object]]
    seeds: Sequence[Mapping[str, object]]
    active_themes: Sequence[str]
    theme_weights: Mapping[str, float] | None
    trip_type: str
    target_count: int
    min_count: int | None = None
    secondary_themes: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class PlannerSelectionResult:
    places: tuple[PlannerPlace, ...]
    reserve: tuple[PlannerPlace, ...]
    audit: dict[str, object]


def build_working_set(selection_input: PlannerSelectionInput) -> PlannerSelectionResult:
    raw_places = tuple(coerce_place(place) for place in selection_input.raw_places)
    soft_places = tuple(coerce_place(place) for place in selection_input.soft_places)
    selected_seed_ids = seed_ids(selection_input.seeds)
    themes = theme_tuple(selection_input.active_themes)
    secondary_themes = tuple(
        theme for theme in theme_tuple(selection_input.secondary_themes) if theme not in themes
    )
    scoped_themes = (*themes, *secondary_themes)
    target_count = positive_int(selection_input.target_count, "target_count")
    min_count_override = (
        None
        if selection_input.min_count is None
        else positive_int(selection_input.min_count, "min_count")
    )
    min_count = bounded_min_place_target(
        selection_input.trip_type,
        target_count,
        min_count_override,
    )
    raw_relevant = tuple(
        with_seed_flag(place, selected_seed_ids)
        for place in raw_places
    )
    raw_kept = tuple(place for place in raw_relevant if _scope_theme(place, scoped_themes) is not None or place.is_seed)

    soft_candidates = tuple(
        with_seed_flag(place, selected_seed_ids)
        for place in soft_places
    )
    soft_on_theme = tuple(place for place in soft_candidates if _scope_theme(place, scoped_themes) is not None)
    soft_off_theme = tuple(place for place in soft_candidates if _scope_theme(place, scoped_themes) is None)
    raw_kept = _merge_raw_soft_overlap(raw_kept, soft_on_theme)
    raw_ids = {place.place_id for place in raw_kept}
    unique_soft_on_theme = tuple(place for place in soft_on_theme if place.place_id not in raw_ids)
    raw_soft_overlap_count = len(soft_on_theme) - len(unique_soft_on_theme)
    merged = merge_by_place_id((*raw_kept, *unique_soft_on_theme))
    quotas = theme_quota(themes, selection_input.theme_weights, target_count)
    selected = select_by_theme_quota(
        ThemeSelectionInput(
            places=merged,
            themes=themes,
            weights=selection_input.theme_weights,
            target_count=target_count,
            sort_key=selection_sort_key,
            theme_key=lambda place: _scope_theme(place, themes),
        ),
    )
    off_theme_excluded_count = sum(1 for place in raw_relevant if _scope_theme(place, scoped_themes) is None)
    subtype_cap = apply_theme_subtype_cap(
        SubtypeCapInput(
            selected=selected,
            pool=merged,
            themes=themes,
            quotas=quotas,
            target_count=target_count,
            min_count=min_count,
            sort_key=selection_sort_key,
            theme_key=lambda place: _scope_theme(place, themes),
        ),
    )
    selected = subtype_cap.places
    selected, preferred_backfill_count = _backfill_secondary_themes(
        selected,
        merged,
        secondary_themes,
        target_count,
    )
    selected, semantic_anchor_seed_ids = _promote_semantic_anchor_seeds(selected, themes)
    selected_ids = {place.place_id for place in selected}
    reserve = tuple(place for place in merged if place.place_id not in selected_ids)
    audit: dict[str, object] = {
        "relevance_ratio": None,
        "relative_threshold": None,
        "raw_relevance_policy": "disabled_use_active_theme_gate",
        "raw_kept_count": len(raw_kept),
        "seed_preserved_count": sum(1 for place in selected if place.is_seed),
        "semantic_anchor_seed_count": len(semantic_anchor_seed_ids),
        "semantic_anchor_seed_ids": semantic_anchor_seed_ids,
        "semantic_anchor_seed_policy": "theme_top1_after_planner_gate",
        "soft_threshold": None,
        "soft_relevance_policy": "disabled_use_theme_gate",
        "soft_on_theme_added_count": len(unique_soft_on_theme),
        "preferred_theme_backfill_count": preferred_backfill_count,
        "preferred_themes": secondary_themes,
        "soft_off_theme_excluded_count": len(soft_off_theme),
        "raw_soft_overlap_count": raw_soft_overlap_count,
        "no_theme_gate_added_count": 0,
        "no_theme_gate_policy": "disabled_by_v2_26_theme_scope",
        "facet_expansion_added_count": 0,
        "off_theme_excluded_count": off_theme_excluded_count + len(soft_off_theme),
        "theme_scope_policy": (
            "active_theme_primary_preferred_theme_secondary"
            if secondary_themes
            else "active_theme_only_no_facet_expansion"
        ),
        "theme_quota": quotas,
        "theme_counts": selected_theme_counts(
            selected,
            themes,
            lambda place: _scope_theme(place, themes),
        ),
        "subtype_counts": subtype_counts(selected),
        "subtype_cap_policy": "per_theme_quota_distinct_subtype_cap",
        "subtype_cap_limit": subtype_cap.limit,
        "subtype_cap_limits": subtype_cap.limits,
        "subtype_cap_relaxed": subtype_cap.relaxed,
        "availability_policy": "unknown_availability_kept_with_audit",
        "profile_cap_policy": "profile_cap_not_applied_without_profile_payload",
    }
    return PlannerSelectionResult(places=selected, reserve=reserve, audit=audit)


def _backfill_secondary_themes(
    selected: tuple[PlannerPlace, ...],
    pool: tuple[PlannerPlace, ...],
    secondary_themes: tuple[str, ...],
    target_count: int,
) -> tuple[tuple[PlannerPlace, ...], int]:
    if not secondary_themes or len(selected) >= target_count:
        return selected, 0
    selected_ids = {place.place_id for place in selected}
    candidates = tuple(
        place
        for place in sorted(pool, key=selection_sort_key, reverse=True)
        if place.place_id not in selected_ids and _scope_theme(place, secondary_themes) is not None
    )
    backfill = candidates[: target_count - len(selected)]
    return (*selected, *backfill), len(backfill)


def _promote_semantic_anchor_seeds(
    places: tuple[PlannerPlace, ...],
    themes: tuple[str, ...],
) -> tuple[tuple[PlannerPlace, ...], tuple[str, ...]]:
    if not places or any(place.is_seed for place in places):
        return places, ()
    anchor_ids = _semantic_anchor_seed_ids(places, themes)
    if not anchor_ids:
        return places, ()
    return (
        tuple(
            with_semantic_seed_source(place, "theme_top1")
            if place.place_id in anchor_ids
            else place
            for place in places
        ),
        anchor_ids,
    )


def _semantic_anchor_seed_ids(
    places: tuple[PlannerPlace, ...],
    themes: tuple[str, ...],
) -> tuple[str, ...]:
    if not themes:
        return ()
    anchor_ids: list[str] = []
    for theme in themes:
        candidates = tuple(place for place in places if _scope_theme(place, themes) == theme)
        if candidates:
            anchor_ids.append(max(candidates, key=selection_sort_key).place_id)
    return tuple(dict.fromkeys(anchor_ids))


def _scope_theme(place: PlannerPlace, themes: tuple[str, ...]) -> str | None:
    if not themes:
        return primary_theme(place, themes)
    active_theme = next((theme for theme in themes if theme in place.theme_tags), None)
    if active_theme is not None:
        return active_theme
    return None


def _merge_raw_soft_overlap(
    raw_places: tuple[PlannerPlace, ...],
    soft_places: tuple[PlannerPlace, ...],
) -> tuple[PlannerPlace, ...]:
    soft_by_id: dict[str, PlannerPlace] = {}
    for place in sorted(soft_places, key=selection_sort_key, reverse=True):
        soft_by_id.setdefault(place.place_id, place)
    return tuple(
        with_soft_channel(place, soft_by_id[place.place_id])
        if place.place_id in soft_by_id
        else place
        for place in raw_places
    )
