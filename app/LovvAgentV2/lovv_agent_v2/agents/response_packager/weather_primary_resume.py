from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lovv_agent_v2.agents.response_packager.packager import package_recommendation_response
from lovv_agent_v2.agents.response_packager.weather_response_context import (
    weather_planner_output,
    weather_recommendation_id,
    weather_request_payload,
    weather_selected_city,
)


def primary_weather_response_update(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    planner_output = weather_planner_output(state)
    return {
        "response": {
            "response_status": "modification_pending",
            "response_payload": package_recommendation_response(
                planner_output=planner_output,
                request=weather_request_payload(state),
                selected_city=weather_selected_city(state, planner_output),
                recommendation_id=weather_recommendation_id(response),
                response_status="modification_pending",
            ),
            "clarification_resume": dict(action),
        },
    }


__all__ = ["primary_weather_response_update"]
