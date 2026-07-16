from __future__ import annotations

from unittest.mock import MagicMock, patch

from lovv_agent_v2.agentcore_entrypoint import handle_v2_invocation


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
@patch("lovv_agent_v2.agentcore_entrypoint._cached_profile_evidence_resolver")
def test_entrypoint_injects_trace_context(
    mock_profile_resolver: MagicMock,
    mock_cached_harness: MagicMock,
) -> None:
    mock_harness = MagicMock()
    mock_harness.invoke.return_value = {
        "response": {"response_payload": {"recommendationId": "REC-1"}},
    }
    mock_cached_harness.return_value = mock_harness
    mock_profile_resolver.return_value.enrich_graph_payload.side_effect = (
        lambda payload, **_: payload
    )

    handle_v2_invocation(
        {
            "entryType": "create",
            "country": "KR",
            "travelMonth": 10,
            "tripType": "2d1n",
            "themes": ["sea_coast"],
            "includeFestivals": False,
            "sessionId": "session-xyz",
            "actorId": "actor-abc",
        },
    )

    payload = mock_harness.invoke.call_args.args[0]
    assert payload["trace"]["recommendation_request_id"] == "session-xyz"
    assert payload["trace"]["thread_id"] == "session-xyz"
    assert payload["trace"]["actor_id"] == "actor-abc"
    assert payload["trace"]["agent_run_id"].startswith("run-")
