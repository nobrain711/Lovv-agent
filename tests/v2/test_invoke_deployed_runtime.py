from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_runner() -> Any:
    module_path = Path(__file__).parents[2] / "scripts" / "invoke_deployed_runtime.py"
    spec = importlib.util.spec_from_file_location("invoke_deployed_runtime", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_payload_with_graph_ids_supplies_agentcore_checkpoint_context() -> None:
    runner = _load_runner()

    payload = runner.payload_with_graph_ids(
        {"entryType": "create", "country": "KR"},
        graph_session_id="showcase-graph-session-0001",
        graph_thread_id=None,
        actor_id=None,
        request_id="showcase-request-0001",
    )

    assert payload["sessionId"] == "showcase-graph-session-0001"
    assert payload["threadId"] == "showcase-graph-session-0001"
    assert payload["actorId"] == "showcase-graph-session-0001"
    assert payload["requestId"] == "showcase-request-0001"
