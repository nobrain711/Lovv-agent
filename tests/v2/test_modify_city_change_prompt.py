from __future__ import annotations

from lovv_agent_v2.agents.intent.modify_prompt_normalizer import normalize_prompt_city_change


def test_prompt_city_change_uses_raw_query_when_llm_omits_city_fields() -> None:
    result = normalize_prompt_city_change(
        {"routing_hint": "city_select_rediscovery"},
        {
            "rawModifyQuery": "도시는 경주로 바꿔줘.",
            "currentOrder": [
                {
                    "itemId": "item-1",
                    "contentId": "attraction#old",
                    "cityId": "KR-47-770",
                },
            ],
        },
    )

    assert result is not None
    assert result["target_city_id"] == "KR-47-130"
    assert result["target_city_name"] == "경주시"
    assert result["avoid_city_ids"] == ["KR-47-770"]
