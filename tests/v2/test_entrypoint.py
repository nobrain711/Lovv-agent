"""Unit tests for V2 entrypoint routing and pseudonymous actor mapping."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from lovv_agent_v2.agentcore_io import extract_thread_id
from lovv_agent_v2.agentcore_entrypoint import (
    extract_actor_id,
    extract_graph_payload,
    extract_request_id,
    extract_resume_value,
    handle_v2_invocation,
)


class FakeProfileEvidenceResolver:
    calls: list[tuple[dict[str, Any], str | None, str | None]] = []

    def enrich_graph_payload(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str | None,
        thread_id: str | None,
    ) -> dict[str, Any]:
        self.calls.append((payload, actor_id, thread_id))
        enriched = dict(payload)
        profile = dict(enriched.get("profile", {}))
        profile["profile_record"] = {
            "actor_id": actor_id,
            "lovv_user_profile": {
                "saved_trip_count": 3,
                "saved_theme_counts": {"sea_coast": 3},
            },
        }
        profile["saved_itinerary_evidence_audit"] = {"cache_status": "hit"}
        enriched["profile"] = profile
        return enriched


def test_extract_actor_id() -> None:
    """Verify that actorId is preferred, and fallback userIds are resolved correctly."""
    # actorId
    assert extract_actor_id({"actorId": "usr-123"}) == "usr-123"
    # actor_id
    assert extract_actor_id({"actor_id": "usr-456"}) == "usr-456"
    # userId
    assert extract_actor_id({"userId": "usr-789"}) == "usr-789"
    # None
    assert extract_actor_id({}) is None


def test_extract_request_id() -> None:
    """Verify extraction of sessionId or requestId."""
    assert extract_request_id({"sessionId": "sess-999"}) == "sess-999"
    assert extract_request_id({"requestId": "req-111"}) == "req-111"
    assert extract_request_id({"headers": {"x-request-id": "hdr-222"}}) == "hdr-222"


def test_extract_thread_id_prefers_session_id_for_checkpoint_resume() -> None:
    assert (
        extract_thread_id(
            {
                "requestId": "per-invocation-request",
                "invocationId": "per-invocation-call",
                "sessionId": "stable-session",
            },
            fallback="per-invocation-request",
        )
        == "stable-session"
    )


def test_extract_resume_value() -> None:
    assert extract_resume_value({"resume": {"optionId": "continue"}}) == {
        "optionId": "continue",
    }
    assert extract_resume_value({"resumeValue": "ok"}) == "ok"
    assert extract_resume_value({"requestId": "REQ-1"}) is None


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
@patch("lovv_agent_v2.agentcore_entrypoint._cached_profile_evidence_resolver")
def test_handle_v2_invocation_plumbing(
    mock_profile_resolver: MagicMock,
    mock_cached_harness: MagicMock,
) -> None:
    """Verify that handle_v2_invocation correctly maps session and actor ids into graph config."""
    mock_harness_instance = MagicMock()
    mock_harness_instance.invoke.return_value = {
        "trace": {"debug": "hidden"},
        "response": {"response_payload": {"recommendationId": "REC-1"}},
    }
    mock_cached_harness.return_value = mock_harness_instance
    fake_resolver = FakeProfileEvidenceResolver()
    fake_resolver.calls.clear()
    mock_profile_resolver.return_value = fake_resolver

    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 10,
        "tripType": "2d1n",
        "themes": ["sea_coast"],
        "includeFestivals": False,
        "sessionId": "session-xyz",
        "actorId": "actor-abc",
    }

    result = handle_v2_invocation(event)

    # harness.invoke가 호출되었는지 검증하고, 전달된 인자 체크
    mock_harness_instance.invoke.assert_called_once()
    args, kwargs = mock_harness_instance.invoke.call_args
    
    # 1. Payload가 제대로 분리되었는지
    payload = args[0]
    assert payload["request"]["country"] == "KR"
    assert "intent" not in payload
    assert payload["profile"]["profile_record"]["actor_id"] == "actor-abc"
    assert payload["profile"]["saved_itinerary_evidence_audit"]["cache_status"] == "hit"
    assert fake_resolver.calls[0][1:] == ("actor-abc", "session-xyz")
    
    # 2. request_id가 sessionId 인지
    assert kwargs["request_id"] == "session-xyz"
    
    # 3. graph_config가 적절한 thread_id와 actor_id를 들고 있는지
    graph_config = kwargs["graph_config"]
    assert graph_config["configurable"]["thread_id"] == "session-xyz"
    assert graph_config["configurable"]["actor_id"] == "actor-abc"
    assert result == {"recommendationId": "REC-1"}


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
def test_handle_v2_invocation_uses_session_id_for_checkpoint_thread(
    mock_cached_harness: MagicMock,
) -> None:
    mock_harness_instance = MagicMock()
    mock_harness_instance.invoke.return_value = {
        "response": {"response_payload": {"recommendationId": "REC-1"}},
    }
    mock_cached_harness.return_value = mock_harness_instance

    handle_v2_invocation(
        {
            "entryType": "chat",
            "country": "KR",
            "travelMonth": 10,
            "tripType": "2d1n",
            "themes": ["sea_coast"],
            "includeFestivals": False,
            "requestId": "per-invocation-request",
            "invocationId": "per-invocation-call",
            "sessionId": "stable-session",
        },
    )

    kwargs = mock_harness_instance.invoke.call_args.kwargs
    assert kwargs["request_id"] == "per-invocation-request"
    assert kwargs["graph_config"]["configurable"]["thread_id"] == "stable-session"


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
def test_handle_v2_invocation_resumes_existing_thread(
    mock_cached_harness: MagicMock,
) -> None:
    mock_harness_instance = MagicMock()
    mock_harness_instance.invoke.return_value = {
        "response": {"response_payload": {"recommendationId": "REC-RESUME"}},
    }
    mock_cached_harness.return_value = mock_harness_instance

    result = handle_v2_invocation(
        {
            "sessionId": "session-xyz",
            "actorId": "actor-abc",
            "resume": {"optionId": "continue_without_festival"},
        },
    )

    payload = mock_harness_instance.invoke.call_args.args[0]
    assert payload.resume == {"optionId": "continue_without_festival"}
    assert result == {"recommendationId": "REC-RESUME"}


@patch("lovv_agent_v2.agentcore_entrypoint._cached_live_harness")
@patch("lovv_agent_v2.agentcore_entrypoint._cached_profile_evidence_resolver")
def test_handle_v2_invocation_continues_when_profile_evidence_lookup_fails(
    mock_profile_resolver: MagicMock,
    mock_cached_harness: MagicMock,
) -> None:
    class RaisingResolver:
        def enrich_graph_payload(
            self,
            payload: dict[str, Any],
            *,
            actor_id: str | None,
            thread_id: str | None,
        ) -> dict[str, Any]:
            raise RuntimeError("profile lookup unavailable")

    mock_harness_instance = MagicMock()
    mock_harness_instance.invoke.return_value = {
        "response": {"response_payload": {"recommendationId": "REC-fallback"}},
    }
    mock_cached_harness.return_value = mock_harness_instance
    mock_profile_resolver.return_value = RaisingResolver()

    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 10,
        "tripType": "2d1n",
        "themes": ["sea_coast"],
        "includeFestivals": False,
        "sessionId": "session-xyz",
        "actorId": "actor-abc",
    }

    result = handle_v2_invocation(event)

    payload = mock_harness_instance.invoke.call_args.args[0]
    assert payload["profile"]["saved_itinerary_evidence_audit"] == {
        "cache_status": "bypassed",
        "fallback_reason": "resolver_failed",
    }
    assert result == {"recommendationId": "REC-fallback"}


def test_extract_graph_payload_wraps_generation_intent_mock() -> None:
    event = {
        "id": "v2_gen_10_history_festival_2d1n",
        "intent_output": {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "active_required_themes": ["역사·전통"],
            "include_festivals": True,
            "cleaned_raw_query": "가을 전통 축제와 유적을 함께 보는 1박 2일 일정이요.",
            "soft_preference_query": "",
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "destination_id": None,
            "user_location": None,
            "unsupported_conditions": [],
        },
    }

    payload = extract_graph_payload(event, request_id="agentcore-session")

    assert payload["request"]["request_id"] == "agentcore-session"
    assert payload["request"]["themes"] == ("역사·전통",)
    assert payload["intent"]["intent_output"]["include_festivals"] is True
    assert payload["profile"] == {}


def test_extract_graph_payload_wraps_public_recommendation_request() -> None:
    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 6,
        "travelYear": 2026,
        "tripType": "daytrip",
        "themes": ["바다·해안"],
        "includeFestivals": False,
        "rawQuery": "조용한 바다 당일치기",
        "congestionPref": "quiet",
        "transportPref": "car",
    }

    payload = extract_graph_payload(event, request_id="REQ-PUBLIC")

    assert payload["request"]["request_id"] == "REQ-PUBLIC"
    assert payload["request"]["themes"] == ("바다·해안",)
    assert payload["request"]["raw_query"] == "조용한 바다 당일치기"
    assert "intent" not in payload


def test_extract_graph_payload_uses_natural_language_query_textfield() -> None:
    event = {
        "entryType": "chat",
        "country": "KR",
        "travelMonth": 10,
        "travelYear": 2026,
        "tripType": "2d1n",
        "themes": ["역사·전통"],
        "includeFestivals": False,
        "naturalLanguageQuery": "속초 말고 안동이나 경주처럼 역사 있는 곳 추천해줘.",
        "softPreferenceQuery": "차분하게 둘러보고 싶어.",
    }

    payload = extract_graph_payload(event, request_id="REQ-TEXTFIELD")

    assert payload["request"]["raw_query"] == event["naturalLanguageQuery"]
    assert payload["request"]["soft_preference_query"] == event["softPreferenceQuery"]
    assert "intent" not in payload


def test_extract_graph_payload_rejects_create_request_without_themes() -> None:
    event = {
        "entryType": "create",
        "country": "KR",
        "travelMonth": 10,
        "travelYear": 2026,
        "tripType": "2d1n",
        "includeFestivals": False,
        "naturalLanguageQuery": "경주 말고 조용한 바다 여행지를 추천해줘.",
    }

    try:
        extract_graph_payload(event, request_id="REQ-INTENT-E2E")
    except ValueError as exc:
        assert "recommendations request" in str(exc)
    else:
        raise AssertionError("theme-less create request must be rejected")
