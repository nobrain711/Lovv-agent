from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.planner.domain.place_model import (
    PlannerPlace,
)
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import DurationLookup, max_leg_min
from lovv_agent_v2.agents.planner.steps.route_days.trim_policy import MAX_HARD_LEG_MIN
from lovv_agent_v2.agents.planner.steps.apply_edit.day_regenerate import apply_day_regenerate
from lovv_agent_v2.agents.planner.steps.apply_edit.current_order_snapshot import request_with_current_order
from lovv_agent_v2.agents.planner.steps.apply_edit.result import (
    applied_update,
    failed_update,
    finalized_update,
)
from lovv_agent_v2.agents.planner.steps.apply_edit.slot_candidates import candidate_pool
from lovv_agent_v2.common.telemetry_lifecycle import emit_modify_result


def apply_edit_node(state: Mapping[str, Any]) -> dict[str, Any]:
    planner = dict(_mapping(state.get("planner")))
    context = dict(_mapping(planner.get("modify_context")))
    for key in ("applied_edit", "failed_edit", "applied_edits", "failed_edits"):
        context.pop(key, None)
    planner["modify_context"] = context
    current_state: Mapping[str, Any] = {**state, "planner": planner}
    modify_intent = _modify_intent(current_state)
    if modify_intent.get("kind") == "day_regenerate":
        return _with_modify_metric(state, apply_day_regenerate(current_state, modify_intent))
    operations = _operations(modify_intent)
    if not operations:
        return _with_modify_metric(
            state,
            failed_update(current_state, _failed_edit("modify_multi_edit_deferred")),
        )
    for operation in operations:
        current_state = _merged_state(current_state, _apply_operation(current_state, operation))
    return _with_modify_metric(state, finalized_update(current_state, len(operations)))


def _apply_operation(state: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    order = current_order(_request(state), state)
    target = _target_item(order, _mapping(operation.get("target")))
    if target is None:
        return failed_update(
            state,
            _failed_edit(
                "modify_target_unresolved",
                requested_target=_mapping(operation.get("target")),
            ),
        )
    candidates = candidate_pool(state, operation, target)
    selected, failed_route_count = _first_feasible_candidate(candidates, order, target)
    if selected is None:
        reason = "slot_replace_route_infeasible" if candidates else "slot_replace_no_candidate"
        return failed_update(
            state,
            _failed_edit(
                reason,
                target=target,
                tried_candidate_count=len(candidates),
                failed_route_candidate_count=failed_route_count,
            ),
        )
    return applied_update(state, operation, order, target, selected, candidates)


def _with_modify_metric(state: Mapping[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    emit_modify_result(state, update)
    return update


def _merged_state(state: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    next_state = dict(state)
    next_state.update(update)
    if "planner" in update:
        next_state["request"] = request_with_current_order(next_state)
    return next_state


def _first_feasible_candidate(
    candidates: Sequence[PlannerPlace],
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> tuple[PlannerPlace | None, int]:
    failed_route_count = 0
    for candidate in candidates:
        if _day_max_leg(order, target, candidate) <= MAX_HARD_LEG_MIN:
            return candidate, failed_route_count
        failed_route_count += 1
    return None, failed_route_count


def _day_max_leg(
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    candidate: PlannerPlace,
) -> float:
    places = tuple(
        candidate if _same_slot(item, target) else _order_place(item)
        for item in sorted(order, key=lambda item: (_int(item.get("day")), _int(item.get("order"))))
        if _int(item.get("day")) == _int(target.get("day"))
    )
    return max_leg_min(places, DurationLookup())


def _order_place(item: Mapping[str, Any]) -> PlannerPlace:
    content_id = _optional_text(item.get("contentId", item.get("content_id"))) or "unknown"
    theme = _optional_text(item.get("theme"))
    return PlannerPlace(
        place_id=content_id,
        title=str(item.get("title", content_id)),
        theme_tags=(theme,) if theme else (),
        similarity=0.0,
        soft_similarity=0.0,
        latitude=_float(item.get("latitude")),
        longitude=_float(item.get("longitude")),
        payload=dict(item),
        is_seed=item.get("isSeed") is True,
    )


def _target_item(
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for item in order:
        if _same_slot(item, target):
            return item
    return None


def _same_slot(item: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    return _int(item.get("day")) == _int(target.get("day")) and _int(item.get("order")) == _int(target.get("order"))


def _operations(modify_intent: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    ops = modify_intent.get("edit_ops")
    return tuple(op for op in ops if isinstance(op, Mapping)) if isinstance(ops, list) else ()


def _failed_edit(reason_code: str, **fields: Any) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "suggested_theme_expansion_options": ("broaden_theme", "active_themes_only"),
        **fields,
    }


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


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _float(value: Any) -> float | None:
    return None if isinstance(value, bool) or not isinstance(value, (int, float)) else float(value)
