from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.intent.modify_city_change import (
    build_city_change,
    city_change_routing_hint,
)
from lovv_agent_v2.agents.intent.modify_current_order import (
    current_order,
    current_order_for_city,
)
from lovv_agent_v2.agents.intent.parser import IntentPreferenceResult, parse_initial_query
from lovv_agent_v2.agents.intent.modify_day_regenerate import day_regenerate_request
from lovv_agent_v2.agents.intent.modify_slots import (
    public_operation,
    slot_replace_operations,
)


def parse_modify_query(raw_query: str) -> IntentPreferenceResult:
    return parse_initial_query(raw_query)


def build_modify_intent(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    raw_query = _required_text(
        request.get("rawModifyQuery", request.get("raw_modify_query")),
        "raw_modify_query",
    )
    base = _modify_base(request, raw_query)
    unsupported_reason = _unsupported_reason(raw_query)
    if unsupported_reason is not None:
        return {
            **base,
            "status": "unsupported",
            "kind": "backlog",
            "edit_ops": [],
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [unsupported_reason],
            "routing_hint": "response_packager_notice",
            "audit": {"parser": "rule_v2"},
        }
    current_order_items = current_order(request, state)
    city_change = build_city_change(raw_query, current_order_for_city(request, state))
    if city_change is not None:
        return {
            **base,
            "status": "ok",
            "kind": "city_change",
            "edit_ops": [],
            "city_change": city_change,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": city_change_routing_hint(city_change),
            "audit": {"parser": "rule_v2"},
        }
    if not current_order_items:
        return missing_current_itinerary_result(base)
    day_regenerate = day_regenerate_request(raw_query, current_order_items)
    if day_regenerate is not None:
        return {
            **base,
            "status": "ok",
            "kind": "day_regenerate",
            "edit_ops": [],
            "day_regenerate": day_regenerate,
            "city_change": None,
            "clarification": None,
            "unsupported_reasons": [],
            "routing_hint": "planner_apply_edit",
            "audit": {"parser": "rule_v2"},
        }
    operations = slot_replace_operations(raw_query, current_order_items)
    if not operations:
        return _clarification_result(
            base,
            reason_code="modify_target_unresolved",
            prompt="어떤 장소를 바꿀까요?",
            options=[],
        )
    ambiguous_operation = _first_operation_with_resolution(operations, "ambiguous")
    if ambiguous_operation is not None:
        return _clarification_result(
            base,
            reason_code="modify_target_ambiguous",
            prompt="어떤 장소를 바꿀까요?",
            options=ambiguous_operation["clarification_options"],
        )
    if _has_duplicate_targets(operations):
        return _clarification_result(
            base,
            reason_code="modify_ops_conflict",
            prompt="같은 장소에 여러 수정 조건이 들어왔습니다. 한 번에 하나씩 바꿔주세요.",
            options=[],
        )
    seed_conflict = _seed_conflict_operation(operations)
    if seed_conflict is not None:
        return _clarification_result(
            base,
            reason_code="modify_seed_theme_conflict",
            prompt="핵심 장소는 같은 테마 안에서만 바꿀 수 있습니다. 같은 테마로 바꿀까요?",
            options=[],
        )
    return {
        **base,
        "status": "ok",
        "kind": "slot_replace",
        "edit_ops": [public_operation(operation) for operation in operations],
        "city_change": None,
        "clarification": None,
        "unsupported_reasons": [],
        "routing_hint": "planner_apply_edit",
        "audit": {"parser": "rule_v2"},
    }


def _first_operation_with_resolution(
    operations: tuple[Mapping[str, Any], ...],
    resolution: str,
) -> Mapping[str, Any] | None:
    for operation in operations:
        if operation["target"]["resolution"] == resolution:
            return operation
    return None


def _has_duplicate_targets(operations: tuple[Mapping[str, Any], ...]) -> bool:
    seen: set[str] = set()
    for operation in operations:
        target = operation["target"]
        item_id = target.get("item_id") or target.get("content_id")
        if item_id is None:
            continue
        if item_id in seen:
            return True
        seen.add(item_id)
    return False


def _seed_conflict_operation(
    operations: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any] | None:
    for operation in operations:
        if operation["seed_policy"]["policy"] == "seed_theme_conflict":
            return operation
    return None


def _modify_base(request: Mapping[str, Any], raw_query: str) -> dict[str, Any]:
    return {
        "intent_type": "modification",
        "thread_id": _required_text(request.get("threadId", request.get("thread_id")), "thread_id"),
        "itinerary_revision": _required_text(
            request.get("itineraryRevision", request.get("itinerary_revision")),
            "itinerary_revision",
        ),
        "destination_id": _optional_text(
            request.get("destinationId", request.get("destination_id")),
        ),
        "raw_modify_query": raw_query,
    }


def _unsupported_reason(raw_query: str) -> str | None:
    if any(keyword in raw_query for keyword in ("추가", "넣어", "더해")):
        return "add_place"
    if any(keyword in raw_query for keyword in ("삭제", "제거", "빼줘")) and "말고" not in raw_query:
        return "remove_place"
    if any(keyword in raw_query for keyword in ("순서", "앞으로", "뒤로")):
        return "reorder_only"
    if any(keyword in raw_query for keyword in ("3박", "4일", "연장", "늘려")):
        return "trip_length_change"
    if any(keyword in raw_query for keyword in ("예약", "예매", "결제")):
        return "reservation_or_booking"
    return None


def _clarification_result(
    base: Mapping[str, Any],
    *,
    reason_code: str,
    prompt: str,
    options: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        **base,
        "status": "needs_clarification",
        "kind": "slot_replace",
        "edit_ops": [],
        "city_change": None,
        "clarification": {
            "reason_code": reason_code,
            "prompt": prompt,
            "options": [dict(option) for option in options],
        },
        "unsupported_reasons": [],
        "routing_hint": "response_packager_wait_user",
        "audit": {"parser": "rule_v2"},
    }


def missing_current_itinerary_result(base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "status": "needs_clarification",
        "kind": "unsupported",
        "reason_code": "modify_missing_current_itinerary",
        "edit_ops": [],
        "city_change": None,
        "clarification": {
            "reason_code": "modify_missing_current_itinerary",
            "prompt": "수정할 기존 일정을 찾지 못했습니다. 먼저 일정을 생성해 주세요.",
            "options": [],
        },
        "unsupported_reasons": ["missing_current_itinerary"],
        "routing_hint": "response_packager_wait_user",
        "audit": {"parser": "rule_v2"},
    }


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        msg = f"{field_name} must be a string"
        raise TypeError(msg)
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must be non-empty"
        raise ValueError(msg)
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
