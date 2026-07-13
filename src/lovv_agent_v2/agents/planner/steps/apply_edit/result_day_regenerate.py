from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace
from lovv_agent_v2.agents.planner.steps.apply_edit.result import (
    _candidate_id,
    _existing_itinerary_item,
    _indoor_outdoor,
    _mapping,
    _mapping_sequence,
    _modify_context,
    _optional_text,
    _planner_group,
    _planner_output,
    _replacement_summary,
    _request_id,
)


def day_regenerate_update(
    state: Mapping[str, Any],
    day: int,
    order: Sequence[Mapping[str, Any]],
    replacements: Sequence[PlannerPlace],
    *,
    full_order: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    planner = _planner_group(state)
    previous_output = _mapping(planner.get("planner_output"))
    replaced_by_order = {
        _int(item.get("order")): replacement
        for item, replacement in zip(sorted(order, key=lambda item: _int(item.get("order"))), replacements)
    }
    itinerary = tuple(
        _day_item(item, replaced_by_order[_int(item.get("order"))])
        if _int(item.get("day")) == day and _int(item.get("order")) in replaced_by_order
        else _existing_itinerary_item(item, previous_output)
        for item in _previous_items(previous_output, full_order)
    )
    changed_slots = [
        {"day": day, "order": item.get("order")}
        for item in sorted(order, key=lambda item: _int(item.get("order")))
    ]
    applied_edit = {
        "request_id": _request_id(state),
        "reason_code": "modify_day_regenerate",
        "day": day,
        "changed_slots": changed_slots,
        "replacements": [_replacement_summary(replacement) for replacement in replacements],
    }
    planner["planner_output"] = _planner_output(previous_output, itinerary, applied_edit)
    planner["validation_result"] = planner["planner_output"]["validation_result"]
    context = _mapping(planner.get("modify_context"))
    planner["modify_context"] = _modify_context(
        planner,
        applied_edit=applied_edit,
        applied_edits=(*_mapping_sequence(context.get("applied_edits")), applied_edit),
        reserve_pool=_remaining_reserve_pool(context.get("reserve_pool"), replacements),
    )
    return {"planner": planner, "memory": _memory_update(state, order)}


def _day_item(item: Mapping[str, Any], replacement: PlannerPlace) -> dict[str, Any]:
    payload = dict(replacement.payload)
    return {
        "day": item.get("day"),
        "order": item.get("order"),
        "slot": item.get("timeOfDay", "modified"),
        "item_type": payload.get("item_type", "attraction"),
        "placeId": replacement.place_id,
        "title": replacement.title,
        "body": "수정 요청에 맞춰 해당 일차를 다시 구성한 방문지입니다.",
        "reason": "같은 도시 안에서 예비 후보 적합성과 이동 가능성을 확인했습니다.",
        "moveMinutes": 0,
        "latitude": replacement.latitude,
        "longitude": replacement.longitude,
        "city_id": payload.get("city_id", item.get("cityId")),
        "city_name_ko": payload.get("city_name_ko"),
        "indoor_outdoor": _indoor_outdoor(payload),
        "theme_tags": replacement.theme_tags,
        "source": payload.get("source"),
        "isSeed": replacement.is_seed,
        "reason_code": "modify_day_regenerate",
        "evidence": {"similarity": replacement.similarity, "soft_similarity": replacement.soft_similarity},
    }


def _previous_items(
    previous_output: Mapping[str, Any],
    full_order: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    items = tuple(
        item
        for item in sorted(
            previous_output.get("itinerary", ()),
            key=lambda value: (_int(_mapping(value).get("day")), _int(_mapping(value).get("order"))),
        )
        if isinstance(item, Mapping)
    )
    if items:
        return items
    return tuple(
        item
        for item in sorted(full_order, key=lambda value: (_int(value.get("day")), _int(value.get("order"))))
        if isinstance(item, Mapping)
    )


def _memory_update(state: Mapping[str, Any], targets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    memory = dict(_mapping(state.get("memory")))
    history = dict(_mapping(memory.get("modify_history")))
    values = list(history.get("replaced_content_ids", ()))
    for target in targets:
        content_id = _optional_text(target.get("contentId", target.get("content_id")))
        if content_id is not None and content_id not in values:
            values.append(content_id)
    history["replaced_content_ids"] = values
    memory["modify_history"] = history
    return memory


def _remaining_reserve_pool(
    value: Any,
    replacements: Sequence[PlannerPlace],
) -> tuple[Mapping[str, Any], ...]:
    replacement_ids = {replacement.place_id for replacement in replacements}
    return tuple(item for item in _mapping_sequence(value) if _candidate_id(item) not in replacement_ids)


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
