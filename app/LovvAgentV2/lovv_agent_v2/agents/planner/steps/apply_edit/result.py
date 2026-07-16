from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace
from lovv_agent_v2.agents.planner.steps.apply_edit.explanation_scope import (
    EXPLANATION_MARKERS,
    explanation_place_ids,
)

REPLACEMENT_NOTICE = "요청한 장소를 같은 일정 안에서 대체했습니다."
PARTIAL_NOTICE_TEMPLATE = "{total}개 수정 중 {applied}개를 반영했고, {failed}개는 반영하지 못했습니다."


def applied_update(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    replacement: PlannerPlace,
    _candidates: Sequence[PlannerPlace],
) -> dict[str, Any]:
    planner = _planner_group(state)
    previous_output = _mapping(planner.get("planner_output"))
    itinerary = tuple(_itinerary_item(item, target, replacement, previous_output) for item in order)
    applied_edit = {
        "request_id": _request_id(state),
        "op_id": operation.get("op_id"),
        "target": _target_summary(target),
        "replacement": _replacement_summary(replacement),
        "changed_slot": {"day": target.get("day"), "order": target.get("order")},
    }
    context = _mapping(planner.get("modify_context"))
    applied_edits = (*_mapping_sequence(context.get("applied_edits")), applied_edit)
    planner["planner_output"] = _planner_output(previous_output, itinerary, applied_edits)
    planner["validation_result"] = planner["planner_output"]["validation_result"]
    planner["modify_context"] = _modify_context(
        planner,
        applied_edit=applied_edit,
        applied_edits=applied_edits,
        reserve_pool=_remaining_reserve_pool(context.get("reserve_pool"), replacement),
    )
    return {"planner": planner, "memory": _memory_update(state, target)}


def failed_update(state: Mapping[str, Any], failed_edit: Mapping[str, Any]) -> dict[str, Any]:
    planner = _planner_group(state)
    context = _mapping(planner.get("modify_context"))
    current_failed = {"request_id": _request_id(state), **dict(failed_edit)}
    planner["modify_context"] = _modify_context(
        planner,
        failed_edit=current_failed,
        failed_edits=(*_mapping_sequence(context.get("failed_edits")), current_failed),
    )
    return {"planner": planner}


def finalized_update(state: Mapping[str, Any], total_edit_count: int) -> dict[str, Any]:
    planner = _planner_group(state)
    context = _mapping(planner.get("modify_context"))
    applied = _mapping_sequence(context.get("applied_edits"))
    failed = _mapping_sequence(context.get("failed_edits"))
    if total_edit_count > 1 and applied and failed:
        previous_output = _mapping(planner.get("planner_output"))
        planner["planner_output"] = _planner_output_with_notice(
            previous_output,
            PARTIAL_NOTICE_TEMPLATE.format(
                total=total_edit_count,
                applied=len(applied),
                failed=len(failed),
            ),
        )
        planner["validation_result"] = planner["planner_output"]["validation_result"]
        planner["modify_context"] = _modify_context(planner)
    result: dict[str, Any] = {"planner": planner}
    memory = state.get("memory")
    if isinstance(memory, Mapping):
        result["memory"] = dict(memory)
    return result


def _planner_output(
    previous_output: Mapping[str, Any],
    itinerary: tuple[dict[str, Any], ...],
    applied_edits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validation = dict(_mapping(previous_output.get("validation_result")))
    for marker in EXPLANATION_MARKERS:
        validation.pop(marker, None)
    validation["planner_status_gate"] = "ok"
    validation["modification_status"] = "applied"
    validation["applied_edit"] = dict(applied_edits[-1])
    validation["explanation_item_place_ids"] = explanation_place_ids(applied_edits)
    notice = _with_notice(previous_output.get("user_notice", ()))
    return {
        "itinerary": itinerary,
        "recommendation_reasons": tuple(previous_output.get("recommendation_reasons", ())),
        "itinerary_flow_reason": previous_output.get("itinerary_flow_reason", "수정 요청을 반영했습니다."),
        "external_links": dict(_mapping(previous_output.get("external_links"))),
        "confidence": previous_output.get("confidence", 0.7),
        "user_notice": notice,
        "validation_result": validation,
        "alternative_itinerary": tuple(previous_output.get("alternative_itinerary", ())),
    }


def _itinerary_item(
    item: Mapping[str, Any],
    target: Mapping[str, Any],
    replacement: PlannerPlace,
    previous_output: Mapping[str, Any],
) -> dict[str, Any]:
    if _same_slot(item, target):
        payload = dict(replacement.payload)
        return {
            "day": item.get("day"),
            "order": item.get("order"),
            "slot": item.get("timeOfDay", "modified"),
            "item_type": payload.get("item_type", "attraction"),
            "placeId": replacement.place_id,
            "title": replacement.title,
            "body": "수정 요청에 맞춰 대체한 방문지입니다.",
            "reason": "기존 슬롯을 유지하면서 후보 적합성과 이동 가능성을 확인했습니다.",
            "moveMinutes": 0,
            "latitude": replacement.latitude,
            "longitude": replacement.longitude,
            "city_id": payload.get("city_id", item.get("cityId")),
            "city_name_ko": payload.get("city_name_ko"),
            "indoor_outdoor": _indoor_outdoor(payload),
            "theme_tags": replacement.theme_tags,
            "source": payload.get("source"),
            "isSeed": item.get("isSeed") is True,
            "reason_code": "modify_slot_replace",
            "evidence": {"similarity": replacement.similarity, "soft_similarity": replacement.soft_similarity},
        }
    return _existing_itinerary_item(item, previous_output)


def _existing_itinerary_item(
    item: Mapping[str, Any],
    previous_output: Mapping[str, Any],
) -> dict[str, Any]:
    content_id = _optional_text(item.get("contentId", item.get("content_id")))
    previous = _previous_item(previous_output, content_id)
    if previous is not None:
        return {**previous, "day": item.get("day"), "order": item.get("order")}
    theme = item.get("theme")
    return {
        "day": item.get("day"),
        "order": item.get("order"),
        "slot": item.get("timeOfDay", "modified"),
        "item_type": item.get("itemType", "attraction"),
        "placeId": content_id,
        "title": item.get("title"),
        "body": "기존 일정 항목입니다.",
        "reason": "기존 일정을 유지했습니다.",
        "moveMinutes": 0,
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "city_id": item.get("cityId"),
        "indoor_outdoor": _indoor_outdoor(item),
        "theme_tags": (theme,) if theme else (),
        "isSeed": item.get("isSeed") is True,
        "reason_code": "modify_unchanged",
        "evidence": {"similarity": 0.0, "soft_similarity": 0.0},
    }


def _previous_item(previous_output: Mapping[str, Any], content_id: str | None) -> dict[str, Any] | None:
    if content_id is None:
        return None
    for item in previous_output.get("itinerary", ()):
        if isinstance(item, Mapping) and item.get("placeId") == content_id:
            return dict(item)
    return None


def _indoor_outdoor(item: Mapping[str, Any]) -> str:
    value = _optional_text(item.get("indoor_outdoor", item.get("indoorOutdoor")))
    if value in {"indoor", "outdoor", "mixed", "unknown"}:
        return value
    return "unknown"


def _modify_context(planner: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    context = dict(_mapping(planner.get("modify_context")))
    context.pop("applied_edit", None)
    context.pop("failed_edit", None)
    context.update(updates)
    return context


def _planner_output_with_notice(
    previous_output: Mapping[str, Any],
    notice: str,
) -> dict[str, Any]:
    output = dict(previous_output)
    output["user_notice"] = _with_extra_notice(previous_output.get("user_notice", ()), notice)
    return output


def _memory_update(state: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    memory = dict(_mapping(state.get("memory")))
    history = dict(_mapping(memory.get("modify_history")))
    content_id = _optional_text(target.get("contentId", target.get("content_id")))
    values = list(history.get("replaced_content_ids", ()))
    if content_id is not None and content_id not in values:
        values.append(content_id)
    history["replaced_content_ids"] = values
    memory["modify_history"] = history
    return memory


def _remaining_reserve_pool(value: Any, replacement: PlannerPlace) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in _mapping_sequence(value) if _candidate_id(item) != replacement.place_id)


def _request_id(state: Mapping[str, Any]) -> str | None:
    request = _mapping(state.get("request"))
    for key in ("requestId", "request_id"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _with_notice(value: Any) -> tuple[str, ...]:
    notices = _notice_tuple(value)
    if REPLACEMENT_NOTICE in notices:
        return notices
    return (*notices, REPLACEMENT_NOTICE)


def _with_extra_notice(value: Any, notice: str) -> tuple[str, ...]:
    notices = _notice_tuple(value)
    return notices if notice in notices else (*notices, notice)


def _notice_tuple(value: Any) -> tuple[str, ...]:
    values = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, Sequence) else ()
    notices: list[str] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        if REPLACEMENT_NOTICE in text:
            if REPLACEMENT_NOTICE not in notices:
                notices.append(REPLACEMENT_NOTICE)
            remainder = text.replace(REPLACEMENT_NOTICE, "").strip()
            if remainder and remainder not in notices:
                notices.append(remainder)
            continue
        if text not in notices:
            notices.append(text)
    return tuple(notices)


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("place_id", candidate.get("placeId", candidate.get("contentId", candidate.get("content_id"))))
    return value.strip() if isinstance(value, str) else ""


def _target_summary(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "content_id": target.get("contentId", target.get("content_id")),
        "title": target.get("title"),
        "day": target.get("day"),
        "order": target.get("order"),
    }


def _replacement_summary(replacement: PlannerPlace) -> dict[str, Any]:
    return {"content_id": replacement.place_id, "title": replacement.title}


def _same_slot(item: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    return _int(item.get("day")) == _int(target.get("day")) and _int(item.get("order")) == _int(target.get("order"))


def _planner_group(state: Mapping[str, Any]) -> dict[str, Any]:
    planner = state.get("planner")
    return dict(planner) if isinstance(planner, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
