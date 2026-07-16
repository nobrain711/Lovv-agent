from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Final, Protocol

from lovv_agent_v2.common.telemetry_metrics import JsonValue
from lovv_agent_v2.common.telemetry_safety import sanitize_text
from lovv_agent_v2.common.telemetry_state import mapping_value, text_value

type MemoryGuardEntry = dict[str, JsonValue]

LOG_TYPE_AGENT_MEMORY_GUARD: Final = "AGENT_MEMORY_GUARD"
DEFAULT_EVENT_PAGE_SIZE: Final = 100


class AgentCoreMemoryEventsClient(Protocol):
    def list_events(self, **request: Any) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class MemoryEventInspection:
    event_guard: str
    event_page_count: int
    has_more_events: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryEventInspector:
    client: AgentCoreMemoryEventsClient
    memory_id: str
    page_size: int = DEFAULT_EVENT_PAGE_SIZE

    def emit_for_state(self, state: Mapping[str, object]) -> None:
        inspection = self.inspect_state(state)
        emit_memory_guard(memory_event_guard_log_entry(inspection))

    def inspect_state(self, state: Mapping[str, object]) -> MemoryEventInspection:
        trace = mapping_value(state.get("trace"))
        session_id = text_value(trace.get("thread_id")) if trace is not None else ""
        actor_id = text_value(trace.get("actor_id")) if trace is not None else ""
        if not session_id or not actor_id:
            return MemoryEventInspection(
                event_guard="agentcore_memory_event_context_missing",
                event_page_count=0,
                has_more_events=False,
            )
        try:
            response = self.client.list_events(
                memoryId=self.memory_id,
                sessionId=session_id,
                actorId=actor_id,
                includePayloads=False,
                maxResults=self.page_size,
            )
        except Exception as exc:  # noqa: BLE001 - observability guard must not block graph execution.
            return MemoryEventInspection(
                event_guard="agentcore_memory_event_check_failed",
                event_page_count=0,
                has_more_events=False,
                error_message=sanitize_text(str(exc) or type(exc).__name__),
            )
        events = response.get("events", ())
        event_count = len(events) if isinstance(events, (list, tuple)) else 0
        has_more = bool(response.get("nextToken"))
        return MemoryEventInspection(
            event_guard=(
                "agentcore_memory_event_page_has_more"
                if has_more
                else "agentcore_memory_event_page_checked"
            ),
            event_page_count=event_count,
            has_more_events=has_more,
        )


def memory_guard_log_entry(
    *,
    memory_mode: str,
    event_guard: str,
    memory_id_configured: bool,
) -> MemoryGuardEntry:
    return {
        "timestamp": _timestamp(),
        "level": "WARN" if memory_mode == "agentcore_memory_saver" else "INFO",
        "logType": LOG_TYPE_AGENT_MEMORY_GUARD,
        "memoryMode": memory_mode,
        "eventGuard": event_guard,
        "memoryIdConfigured": memory_id_configured,
    }


def memory_event_guard_log_entry(inspection: MemoryEventInspection) -> MemoryGuardEntry:
    entry = memory_guard_log_entry(
        memory_mode="agentcore_memory_saver",
        event_guard=inspection.event_guard,
        memory_id_configured=True,
    )
    entry["level"] = (
        "WARN"
        if inspection.has_more_events or inspection.error_message is not None
        else "INFO"
    )
    entry["eventPageCount"] = inspection.event_page_count
    entry["hasMoreEvents"] = inspection.has_more_events
    if inspection.error_message is not None:
        entry["errorMessage"] = inspection.error_message[:300]
    return entry


def emit_memory_guard(entry: MemoryGuardEntry) -> None:
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = [
    "AgentCoreMemoryEventsClient",
    "LOG_TYPE_AGENT_MEMORY_GUARD",
    "MemoryEventInspection",
    "MemoryEventInspector",
    "emit_memory_guard",
    "memory_event_guard_log_entry",
    "memory_guard_log_entry",
]
