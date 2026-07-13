from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.weather_alternative.node import (
    weather_alternative_node,
)
from lovv_agent_v2.agents.planner.steps.weather_alternative.exposure import item_exposure
from lovv_agent_v2.agents.planner.steps.weather_alternative.policy import (
    WeatherDecisionPolicy,
    decide_weather,
)
from lovv_agent_v2.agents.planner.steps.weather_alternative.resource import (
    WeatherRiskIndex,
    WeatherRiskRow,
)
from lovv_agent_v2.tools.destination_policy import normalize_attraction_candidate
from lovv_agent_v2.agents.planner.agent import _candidate_payload
from lovv_agent_v2.agents.supervisor.router import route_next_action


def test_weather_policy_offers_alternative_when_high_risk_outdoor_ratio_is_high() -> None:
    risk = WeatherRiskRow(
        city_id="KR-TEST",
        month=7,
        overall="high",
        dimensions={"rain": "high"},
        reason_codes=("rain_heavy",),
    )

    decision = decide_weather(
        risk,
        known_count=4,
        sensitive_count=2,
        policy=WeatherDecisionPolicy(),
    )

    assert decision.status == "alternative_available"
    assert decision.notice_level == "strong"
    assert decision.should_offer_alternative is True
    assert "평년 기준" in (decision.notice or "")
    assert "비" in (decision.notice or "")


def test_weather_policy_uses_heat_notice_when_heat_is_primary_dimension() -> None:
    risk = WeatherRiskRow(
        city_id="KR-TEST",
        month=8,
        overall="high",
        dimensions={"heat": "high", "rain": "low"},
        reason_codes=("avg_high_c_gte_global_p90",),
    )

    decision = decide_weather(
        risk,
        known_count=4,
        sensitive_count=2,
        policy=WeatherDecisionPolicy(),
    )

    assert "더위" in (decision.notice or "")
    assert "한낮" in (decision.notice or "")


def test_weather_policy_uses_cold_notice_when_cold_is_primary_dimension() -> None:
    risk = WeatherRiskRow(
        city_id="KR-TEST",
        month=1,
        overall="high",
        dimensions={"cold": "high", "rain": "low"},
        reason_codes=("avg_low_c_lte_global_p10",),
    )

    decision = decide_weather(
        risk,
        known_count=4,
        sensitive_count=1,
        policy=WeatherDecisionPolicy(),
    )

    assert "추위" in (decision.notice or "")
    assert "방한" in (decision.notice or "")


def test_weather_policy_ignores_unknown_only_exposure() -> None:
    risk = WeatherRiskRow(
        city_id="KR-TEST",
        month=7,
        overall="high",
        dimensions={"rain": "high"},
        reason_codes=("rain_heavy",),
    )

    decision = decide_weather(
        risk,
        known_count=0,
        sensitive_count=0,
        policy=WeatherDecisionPolicy(),
    )

    assert decision.status == "unknown_exposure"
    assert decision.notice is None
    assert decision.should_offer_alternative is False


def test_weather_exposure_uses_enriched_detail_metadata() -> None:
    item = {"details": {"indoor_outdoor": "outdoor"}}

    assert item_exposure(item) == "outdoor"


def test_planner_candidate_payload_promotes_weather_metadata() -> None:
    candidate = normalize_attraction_candidate(
        {
            "key": "attraction#1#0",
            "distance": 0.2,
            "metadata": {
                "entity_type": "attraction",
                "city_id": "KR-TEST",
                "title": "해변",
                "theme_tags": ["바다·해안"],
                "indoor_outdoor": "outdoor",
                "attraction_subtype_code": "NA020900",
            },
        },
    )

    payload = _candidate_payload(candidate)

    assert payload["indoor_outdoor"] == "outdoor"
    assert payload["attraction_subtype_code"] == "NA020900"


def test_weather_node_adds_notice_and_audit_from_runtime_index() -> None:
    index = WeatherRiskIndex(
        (
            WeatherRiskRow(
                city_id="KR-TEST",
                month=7,
                overall="medium",
                dimensions={"heat": "medium"},
                reason_codes=("hot_month",),
            ),
        ),
    )
    state = {
        "intent": {"city_select_input": {"travel_month": 7}},
        "runtime": {"weather_risk_index": index},
        "planner": {
            "planner_output": {
                "itinerary": (
                    {"placeId": "p1", "city_id": "KR-TEST", "indoor_outdoor": "outdoor"},
                    {"placeId": "p2", "city_id": "KR-TEST", "indoor_outdoor": "indoor"},
                ),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {"planner_status_gate": "ok"},
                "alternative_itinerary": (),
            },
        },
    }

    result = weather_alternative_node(state)

    planner_output = result["planner"]["planner_output"]
    weather_audit = planner_output["validation_result"]["weather_audit"]
    assert planner_output["user_notice"]
    assert weather_audit["status"] == "notice"
    assert weather_audit["evaluation_stage"] == "planner"
    assert weather_audit["known_item_count"] == 2
    assert weather_audit["weather_sensitive_item_count"] == 1


def test_weather_node_does_not_duplicate_existing_notice() -> None:
    notice = "선택한 도시의 해당 월은 평년 기준 낮 더위가 있는 편이라, 한낮 야외 일정은 무리하지 않게 조정하는 것이 좋습니다."
    index = WeatherRiskIndex(
        (
            WeatherRiskRow(
                city_id="KR-TEST",
                month=7,
                overall="medium",
                dimensions={"heat": "medium"},
                reason_codes=("hot_month",),
            ),
        ),
    )
    state = {
        "intent": {"city_select_input": {"travel_month": 7}},
        "runtime": {"weather_risk_index": index},
        "planner": {
            "planner_output": {
                "itinerary": (
                    {"placeId": "p1", "city_id": "KR-TEST", "indoor_outdoor": "outdoor"},
                    {"placeId": "p2", "city_id": "KR-TEST", "indoor_outdoor": "indoor"},
                ),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (notice,),
                "validation_result": {"planner_status_gate": "ok"},
                "alternative_itinerary": (),
            },
        },
    }

    planner_output = weather_alternative_node(state)["planner"]["planner_output"]

    assert planner_output["user_notice"] == (notice,)


def test_weather_node_marks_city_missing_from_weather_map_as_unavailable() -> None:
    state = {
        "intent": {"city_select_input": {"travel_month": 7}},
        "runtime": {"weather_risk_index": WeatherRiskIndex(())},
        "planner": {
            "planner_output": {
                "itinerary": (
                    {"placeId": "p1", "city_id": "KR-MISSING", "indoor_outdoor": "outdoor"},
                ),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {"planner_status_gate": "ok"},
                "alternative_itinerary": (),
            },
        },
    }

    result = weather_alternative_node(state)

    planner_output = result["planner"]["planner_output"]
    weather_audit = planner_output["validation_result"]["weather_audit"]
    assert planner_output["user_notice"] == ()
    assert weather_audit["status"] == "unavailable"
    assert weather_audit["unavailable_reason"] == "city_weather_map_missing"


def test_weather_node_marks_empty_itinerary_as_processed_after_explain() -> None:
    state = {
        "intent": {"city_select_input": {"travel_month": 7}},
        "planner": {
            "planner_output": {
                "itinerary": (),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {
                    "planner_status_gate": "insufficient_candidates",
                    "planner_copy_generation_used_llm": False,
                },
                "alternative_itinerary": (),
            },
        },
    }

    result = weather_alternative_node(state)

    validation = result["planner"]["planner_output"]["validation_result"]
    assert validation["weather_audit"]["evaluation_stage"] == "post_explain"
    assert validation["weather_audit"]["status"] == "unavailable"
    assert validation["weather_audit"]["unavailable_reason"] == "empty_itinerary"


def test_supervisor_routes_post_explain_state_to_weather_before_packager() -> None:
    state = {
        "profile": {"audit": {}},
        "festival_gate": {"audit": {}},
        "city_select": {"city_selection_result": {"selected_city": {"city_id": "KR-TEST"}}},
        "planner": {
            "planner_output": {
                "itinerary": (),
                "recommendation_reasons": (),
                "itinerary_flow_reason": "",
                "external_links": {},
                "confidence": 0.7,
                "user_notice": (),
                "validation_result": {
                    "planner_status_gate": "ok",
                    "planner_copy_generation_used_llm": True,
                    "weather_audit": {"evaluation_stage": "planner"},
                },
                "alternative_itinerary": (),
            },
            "validation_result": {
                "planner_status_gate": "ok",
                "planner_copy_generation_used_llm": True,
                "weather_audit": {"evaluation_stage": "planner"},
            },
        },
    }

    assert route_next_action(state) == "weather_alternative"
