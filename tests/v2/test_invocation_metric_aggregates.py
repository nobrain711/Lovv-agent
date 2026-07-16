from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lovv_agent_v2.common.telemetry_metrics import record_step_duration, record_tool_call
from lovv_agent_v2.common.telemetry_threading import submit_with_context
from lovv_agent_v2.common.telemetry_memory import MemoryEventInspector
from lovv_agent_v2.harness import LovvLangGraphV2Harness
from lovv_agent_v2.infra.config import RuntimeConfig


@dataclass(slots=True)
class InstrumentedGraph:
    def invoke(
        self,
        payload: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_step_duration("planner.retrieve_places", 12)
        record_tool_call("s3vectors", "QueryVectors", 34)
        return {"response": {"response_status": "modification_pending"}}


@dataclass(slots=True)
class ThreadedToolGraph:
    def invoke(
        self,
        payload: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del payload, config
        with ThreadPoolExecutor(max_workers=1) as executor:
            submit_with_context(
                executor,
                lambda: record_tool_call("bedrock", "InvokeModel", 17),
            ).result()
        return {"response": {"response_status": "completed"}}


@dataclass(slots=True)
class FakeAgentCoreEvents:
    requests: list[dict[str, Any]]

    def list_events(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"events": [{} for _ in range(100)], "nextToken": "more"}


def test_harness_emits_invocation_metric(capsys) -> None:
    harness = LovvLangGraphV2Harness(graph=InstrumentedGraph(), config=RuntimeConfig())

    harness.invoke({"request": {"request_id": "REQ-1"}})

    output = capsys.readouterr().out
    assert '"logType":"AGENT_INVOCATION_METRIC"' in output
    assert '"requestId":"REQ-1"' in output
    assert '"status":"success"' in output
    assert '"stepMetrics":{"planner.retrieve_places"' in output
    assert '"toolMetrics":{"s3vectors.QueryVectors"' in output


def test_harness_emits_agentcore_memory_event_guard(capsys) -> None:
    events = FakeAgentCoreEvents(requests=[])
    harness = LovvLangGraphV2Harness(
        graph=InstrumentedGraph(),
        config=RuntimeConfig(),
        runtime={
            "memory_event_inspector": MemoryEventInspector(
                client=events,
                memory_id="memory-1",
            ),
        },
    )

    harness.invoke(
        {"request": {"request_id": "REQ-1"}},
        graph_config={"configurable": {"thread_id": "THREAD-1", "actor_id": "ACTOR-1"}},
    )

    output = capsys.readouterr().out
    assert events.requests == [
        {
            "memoryId": "memory-1",
            "sessionId": "THREAD-1",
            "actorId": "ACTOR-1",
            "includePayloads": False,
            "maxResults": 100,
        }
    ]
    assert '"logType":"AGENT_MEMORY_GUARD"' in output
    assert '"eventGuard":"agentcore_memory_event_page_has_more"' in output
    assert '"eventPageCount":100' in output


def test_harness_aggregates_tool_metrics_from_worker_thread(capsys) -> None:
    harness = LovvLangGraphV2Harness(graph=ThreadedToolGraph(), config=RuntimeConfig())

    harness.invoke({"request": {"request_id": "REQ-THREAD"}})

    output = capsys.readouterr().out
    assert '"toolMetrics":{"bedrock.InvokeModel"' in output
