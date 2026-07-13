from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResponsePackagerInput:
    request: Mapping[str, Any]
    planner_output: Mapping[str, Any] | None
    selected_city: Mapping[str, Any] | None
    festival_verifications: Sequence[Any]
    unsupported_conditions: Sequence[str]
    clarification: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class ResponsePackagerOutput:
    response: dict[str, Any]


__all__ = ["ResponsePackagerInput", "ResponsePackagerOutput"]
