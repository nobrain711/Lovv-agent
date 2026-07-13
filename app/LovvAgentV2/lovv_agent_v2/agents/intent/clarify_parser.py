from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_clarify_intent(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    selected_option_id = _selected_option_id(request)
    thread_id = _text(request.get("threadId", request.get("thread_id")))
    option = _pending_option(state, selected_option_id)
    if selected_option_id is not None and option is not None:
        return {
            "intent_type": "clarify",
            "status": "resolved",
            "thread_id": thread_id,
            "selected_option_id": selected_option_id,
            "resume": {"option_id": selected_option_id},
            "clarification_resume": option,
            "audit": {"matched_label": option["label"]},
        }
    raw_query = _text(request.get("rawQuery", request.get("raw_query")))
    result: dict[str, Any] = {
        "intent_type": "clarify",
        "status": "needs_clarification",
        "thread_id": thread_id,
        "raw_clarify_query": raw_query,
        "selected_option_id": None,
        "reason_code": "clarify_option_unresolved",
    }
    return result


def _selected_option_id(request: Mapping[str, Any]) -> str | None:
    return _text(
        request.get(
            "selectedOptionId",
            request.get("selected_option_id", request.get("optionId")),
        ),
    )


def _pending_option(
    state: Mapping[str, Any],
    selected_option_id: str | None,
) -> Mapping[str, Any] | None:
    if selected_option_id is None:
        return None
    for clarification in _pending_clarifications(state):
        options = clarification.get("options")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            continue
        for option in options:
            if not isinstance(option, Mapping):
                continue
            option_id = _text(option.get("option_id", option.get("optionId")))
            label = _text(option.get("label"))
            if (
                option_id is not None
                and option_id == selected_option_id
                and label is not None
            ):
                return {
                    "option_id": option_id,
                    "label": label,
                    "reason_code": _text(
                        clarification.get(
                            "reason_code",
                            clarification.get("reasonCode"),
                        ),
                    ),
                    "apply": _mapping_or_empty(option.get("apply")),
                    "then": _text(option.get("then")),
                }
    return None


def _pending_clarifications(
    state: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    clarifications: list[Mapping[str, Any]] = []
    for group_name in ("intent", "memory", "festival_gate", "city_select", "response"):
        group = state.get(group_name)
        if not isinstance(group, Mapping):
            continue
        clarification = group.get("pending_clarification")
        if isinstance(clarification, Mapping):
            clarifications.append(clarification)
        clarification = group.get("clarification")
        if isinstance(clarification, Mapping):
            clarifications.append(clarification)
    return tuple(clarifications)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
