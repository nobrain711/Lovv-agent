from __future__ import annotations

import datetime as dt
import importlib.util
import os
from pathlib import Path
from typing import Any


def _load_runner() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "v2" / "run_general_live_smoke.py"
    spec = importlib.util.spec_from_file_location("run_general_live_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_event_with_runtime_ids_defaults_thread_to_session() -> None:
    runner = _load_runner()

    event = runner.event_with_runtime_ids(
        {"entryType": "modify", "rawModifyQuery": "도시는 강릉으로 바꿔줘."},
        session_id="session-1",
        thread_id=None,
        actor_id="actor-1",
        request_id=None,
    )

    assert event["sessionId"] == "session-1"
    assert event["threadId"] == "session-1"
    assert event["actorId"] == "actor-1"
    assert event["requestId"] == "session-1-modify"


def test_mirror_aws_region_sets_standard_region_env(monkeypatch: Any) -> None:
    runner = _load_runner()
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    runner.mirror_aws_region({"LOVV_AWS_REGION": "us-east-1"})

    assert os.environ["AWS_REGION"] == "us-east-1"
    assert os.environ["AWS_DEFAULT_REGION"] == "us-east-1"


def test_summarize_response_reports_destination_and_item_counts() -> None:
    runner = _load_runner()

    summary = runner.summarize_response(
        {"entryType": "create", "sessionId": "s-1", "threadId": "s-1"},
        {
            "recommendationId": "rec-1",
            "destination": {"destinationId": "KR-51-170", "name": "동해시"},
            "itinerary": {"days": [{"items": [{}, {}]}, {"items": [{}]}]},
        },
        started_at=dt.datetime.now(dt.UTC),
    )

    assert summary["entryType"] == "create"
    assert summary["destinationId"] == "KR-51-170"
    assert summary["destinationName"] == "동해시"
    assert summary["dayCount"] == 2
    assert summary["itemCount"] == 3
