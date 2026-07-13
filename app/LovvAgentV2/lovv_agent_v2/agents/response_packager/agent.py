from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.response_packager.contracts import (
    ResponsePackagerInput,
    ResponsePackagerOutput,
)
from lovv_agent_v2.agents.response_packager.packager import (
    package_recommendation_response,
)


@dataclass(frozen=True, slots=True)
class ResponsePackagerAgent:
    def run(self, request: ResponsePackagerInput) -> ResponsePackagerOutput:
        response_status = (
            "END_WAIT_USER"
            if request.clarification is not None
            else "modification_pending"
        )
        payload = package_recommendation_response(
            planner_output=request.planner_output,
            request=request.request,
            selected_city=request.selected_city,
            festival_verifications=request.festival_verifications,
            unsupported_conditions=request.unsupported_conditions,
            recommendation_id=_recommendation_id(request.request),
            response_status=response_status,
            clarification=request.clarification,
        )
        return ResponsePackagerOutput(
            response={
                "response_status": response_status,
                "response_payload": payload,
                "clarification": request.clarification,
            },
        )


def _recommendation_id(request: Mapping[str, Any]) -> str | None:
    value = request.get("request_id", request.get("requestId"))
    return value if isinstance(value, str) else None


__all__ = ["ResponsePackagerAgent"]
