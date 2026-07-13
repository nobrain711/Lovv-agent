from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.models.schemas import CitySelectInput


@dataclass(frozen=True, slots=True)
class FestivalVerifierInput:
    city_input: CitySelectInput
    candidate_payloads: tuple[Mapping[str, Any], ...] = ()
    city_key: str | None = None


@dataclass(frozen=True, slots=True)
class FestivalVerifierOutput:
    festival_gate: dict[str, Any]

    def to_state(self) -> dict[str, Any]:
        return {"festival_gate": self.festival_gate}


__all__ = ["FestivalVerifierInput", "FestivalVerifierOutput"]
