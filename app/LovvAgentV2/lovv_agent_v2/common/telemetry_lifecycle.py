from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from threading import Lock
from typing import Final

from lovv_agent_v2.common.telemetry_metrics import JsonValue
from lovv_agent_v2.common.telemetry_state import mapping_value, request_mapping, text_value
from lovv_agent_v2.core.state import UnifiedAgentState

LOG_TYPE_AGENT_LIFECYCLE_METRIC: Final = "AGENT_LIFECYCLE_METRIC"
_CLARIFICATION_KEYS: set[tuple[str, str]] = set()
_CLARIFICATION_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class LifecycleMetric:
    lifecycle_type: str
    event: str
    request_id: str
    details: Mapping[str, JsonValue]


def emit_lifecycle_metric(metric: LifecycleMetric) -> None:
    payload: dict[str, JsonValue] = {
        "timestamp": _timestamp(),
        "level": "INFO",
        "logType": LOG_TYPE_AGENT_LIFECYCLE_METRIC,
        "requestId": metric.request_id,
        "lifecycleType": metric.lifecycle_type,
        "event": metric.event,
        "details": dict(metric.details),
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def emit_clarification_waiting(state: UnifiedAgentState, response: Mapping[str, object]) -> None:
    payload = mapping_value(response.get("response_payload"))
    clarification = mapping_value(payload.get("clarification")) if payload is not None else None
    if clarification is None:
        return
    options = _mapping_sequence(clarification.get("options"))
    reason_code = _reason_code(clarification)
    request_id = _request_id(state)
    if _clarification_seen(request_id, reason_code):
        return
    emit_lifecycle_metric(
        LifecycleMetric(
            lifecycle_type="clarification",
            event="waiting",
            request_id=request_id,
            details={
                "reasonCode": reason_code,
                "optionCount": len(options),
                "thenValues": _then_values(options),
            },
        )
    )


def emit_modify_result(state: Mapping[str, object], update: Mapping[str, object]) -> None:
    planner = mapping_value(update.get("planner"))
    context = mapping_value(planner.get("modify_context")) if planner is not None else None
    if context is None:
        return
    applied = _mapping_sequence(context.get("applied_edits"))
    failed = _mapping_sequence(context.get("failed_edits"))
    if not applied and not failed:
        return
    emit_lifecycle_metric(
        LifecycleMetric(
            lifecycle_type="modify",
            event=_modify_event(applied, failed),
            request_id=_request_id(state),
            details={
                "appliedEditCount": len(applied),
                "failedEditCount": len(failed),
                "failedReasonCodes": _reason_codes(failed),
            },
        )
    )


def emit_weather_result(state: UnifiedAgentState, planner: Mapping[str, object]) -> None:
    audit = mapping_value(planner.get("weather_risk"))
    if audit is None:
        return
    emit_lifecycle_metric(
        LifecycleMetric(
            lifecycle_type="weather",
            event="evaluated",
            request_id=_request_id(state),
            details={
                "status": text_value(audit.get("status")),
                "evaluationStage": text_value(audit.get("evaluation_stage")),
                "noticeLevel": text_value(audit.get("notice_level")),
                "unavailableReason": text_value(audit.get("unavailable_reason")),
                "alternativeGenerationStatus": text_value(audit.get("alternative_generation_status")),
            },
        )
    )


def _modify_event(
    applied: Sequence[Mapping[str, object]],
    failed: Sequence[Mapping[str, object]],
) -> str:
    if applied and failed:
        return "partial"
    if applied:
        return "applied"
    return "failed"


def _reason_code(clarification: Mapping[str, object]) -> str:
    value = text_value(clarification.get("reasonCode")) or text_value(clarification.get("reason_code"))
    return value or "unknown"


def _clarification_seen(request_id: str, reason_code: str) -> bool:
    key = (request_id, reason_code)
    with _CLARIFICATION_LOCK:
        if key in _CLARIFICATION_KEYS:
            return True
        _CLARIFICATION_KEYS.add(key)
        return False


def _then_values(options: Sequence[Mapping[str, object]]) -> list[JsonValue]:
    return [then for option in options if isinstance(then := option.get("then"), str)]


def _reason_codes(failed: Sequence[Mapping[str, object]]) -> list[JsonValue]:
    return [reason for item in failed if isinstance(reason := item.get("reason_code"), str)]


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _request_id(state: Mapping[str, object]) -> str:
    request = request_mapping(state)
    for key in ("request_id", "requestId"):
        value = text_value(request.get(key))
        if value:
            return value
    return "unknown"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "LOG_TYPE_AGENT_LIFECYCLE_METRIC",
    "LifecycleMetric",
    "emit_clarification_waiting",
    "emit_lifecycle_metric",
    "emit_modify_result",
    "emit_weather_result",
]
