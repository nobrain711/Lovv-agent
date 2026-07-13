from __future__ import annotations

from collections.abc import Mapping


def planner_group(state: Mapping[str, object]) -> dict[str, object]:
    planner = state.get("planner")
    return dict(planner) if isinstance(planner, Mapping) else {}


def planner_scratch(state: Mapping[str, object]) -> dict[str, object]:
    scratch = planner_group(state).get("scratch")
    return dict(scratch) if isinstance(scratch, Mapping) else {}


def planner_scratch_mapping(
    state: Mapping[str, object],
    key: str,
    field_name: str,
) -> Mapping[str, object]:
    value = planner_scratch(state).get(key)
    if not isinstance(value, Mapping):
        from lovv_agent_v2.models.schemas import SchemaValidationError

        raise SchemaValidationError(f"{field_name} must be an object")
    return value


def planner_state_update(
    state: Mapping[str, object],
    *,
    public_updates: Mapping[str, object] | None = None,
    scratch_updates: Mapping[str, object] | None = None,
) -> dict[str, object]:
    planner = planner_group(state)
    scratch = planner_scratch(state)
    if scratch_updates is not None:
        scratch.update(dict(scratch_updates))
        planner["scratch"] = scratch
    if public_updates is not None:
        planner.update(dict(public_updates))
    return {"planner": planner}
