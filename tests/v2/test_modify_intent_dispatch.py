from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.intent import modify_dispatch


def test_resolve_modify_intent_keeps_rule_day_regenerate_without_prompt(monkeypatch: Any) -> None:
    def fail_prompt(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("day_regenerate rule parse should not call modify prompt fallback")

    monkeypatch.setattr(modify_dispatch, "prompt_modify_intent_from_request", fail_prompt)

    result = modify_dispatch.resolve_modify_intent(
        {
            "runtime": {
                "intent_prompt_runtime": {
                    "runtime": _fake_runtime,
                    "schema_retry_limit": 0,
                },
            },
        },
        _day_regenerate_request(),
    )

    assert result["kind"] == "day_regenerate"
    assert result["day_regenerate"]["day"] == 1


def _day_regenerate_request() -> Mapping[str, Any]:
    return {
        "entryType": "modify",
        "threadId": "thread-001",
        "itineraryRevision": "rev-001",
        "rawModifyQuery": "1일차 전체 바꿔줘.",
        "currentOrder": [
            {"itemId": "item-1", "contentId": "attraction#one", "day": 1, "order": 1},
            {"itemId": "item-2", "contentId": "attraction#two", "day": 1, "order": 2},
        ],
    }


def _fake_runtime(*_args: object, **_kwargs: object) -> dict[str, object]:
    return {}
