from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node
from lovv_agent_v2.agents.planner.steps.weather_alternative.node import weather_alternative_node
from lovv_agent_v2.agents.planner.steps.weather_alternative.resource import (
    WeatherRiskIndex,
    WeatherRiskRow,
)
from lovv_agent_v2.agents.response_packager.node import response_packager_node


def test_apply_edit_emits_modify_lifecycle_metric(capsys) -> None:
    apply_edit_node(
        {
            "request": _request_current_order(),
            "intent": _slot_replace_intent(),
            "planner": {
                "planner_output": _planner_output(),
                "modify_context": {
                    "reserve_pool": [_candidate("attraction#new", "경주 숲길", (35.833, 129.219))]
                },
            },
        },
    )

    output = capsys.readouterr().out
    assert '"logType":"AGENT_LIFECYCLE_METRIC"' in output
    assert '"lifecycleType":"modify"' in output
    assert '"event":"applied"' in output
    assert '"appliedEditCount":1' in output


def test_response_packager_emits_clarification_lifecycle_metric(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "lovv_agent_v2.agents.response_packager.node.interrupt",
        lambda payload: {"selectedOptionId": payload["clarification"]["options"][0]["optionId"]},
    )

    response_packager_node(
        {
            "request": {"request_id": "REQ-MODIFY"},
            "intent": {"modify_intent": {"kind": "slot_replace"}},
            "planner": {
                "modify_context": {
                    "failed_edit": {"reason_code": "slot_replace_no_candidate"},
                },
            },
        },
    )

    output = capsys.readouterr().out
    assert '"lifecycleType":"clarification"' in output
    assert '"reasonCode":"slot_replace_no_candidate"' in output
    assert '"optionCount":2' in output


def test_weather_node_emits_weather_lifecycle_metric(capsys) -> None:
    weather_alternative_node(
        {
            "request": {"request_id": "REQ-WEATHER"},
            "intent": {"city_select_input": {"travel_month": 7}},
            "runtime": {"weather_risk_index": _weather_index()},
            "planner": {"planner_output": _weather_planner_output()},
        },
    )

    output = capsys.readouterr().out
    assert '"lifecycleType":"weather"' in output
    assert '"event":"evaluated"' in output
    assert '"status":"notice"' in output


def _request_current_order() -> dict[str, object]:
    return {
        "request_id": "REQ-MODIFY",
        "currentOrder": [
            {
                "contentId": "attraction#seed",
                "title": "경주 교촌마을",
                "day": 1,
                "order": 1,
                "latitude": 35.8296,
                "longitude": 129.2147,
                "theme": "역사·전통",
            },
            {
                "contentId": "attraction#old",
                "title": "경주 오래된 숲",
                "day": 1,
                "order": 2,
                "latitude": 35.832,
                "longitude": 129.218,
                "theme": "역사·전통",
            },
            {
                "contentId": "attraction#last",
                "title": "육부전",
                "day": 1,
                "order": 3,
                "latitude": 35.837,
                "longitude": 129.22,
                "theme": "역사·전통",
            },
        ],
    }


def _slot_replace_intent() -> dict[str, object]:
    return {
        "modify_intent": {
            "kind": "slot_replace",
            "edit_ops": [
                {
                    "op_id": "op-1",
                    "target": {"day": 1, "order": 2, "content_id": "attraction#old"},
                    "condition": {"theme": "역사·전통"},
                    "seed_policy": {"target_is_seed": False, "policy": "not_seed"},
                },
            ],
        },
    }


def _planner_output() -> dict[str, object]:
    return {
        "itinerary": (),
        "recommendation_reasons": (),
        "itinerary_flow_reason": "",
        "external_links": {},
        "confidence": 0.7,
        "user_notice": (),
        "validation_result": {"planner_status_gate": "ok"},
    }


def _weather_planner_output() -> dict[str, object]:
    return {
        **_planner_output(),
        "itinerary": ({"placeId": "p1", "city_id": "KR-TEST", "indoor_outdoor": "outdoor"},),
        "alternative_itinerary": (),
    }


def _weather_index() -> WeatherRiskIndex:
    return WeatherRiskIndex(
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


def _candidate(
    place_id: str,
    title: str,
    coords: tuple[float, float],
) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "latitude": coords[0],
        "longitude": coords[1],
        "theme_tags": ("역사·전통",),
        "similarity": 0.9,
    }
