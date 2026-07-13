from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lovv_agent_v2.agents.festival_verifier.gate_result import FestivalStatusCandidate


def build_festival_audit(
    *,
    travel_month: int,
    target_year: int | None,
    requested_destination_id: str | None,
    confirmed: Sequence[FestivalStatusCandidate],
    tentative: Sequence[FestivalStatusCandidate],
    excluded: Sequence[FestivalStatusCandidate],
) -> dict[str, Any]:
    return {
        "travel_month": travel_month,
        "target_year": target_year,
        "requested_destination_id": requested_destination_id,
        "candidate_counts": {
            "confirmed": len(confirmed),
            "tentative": len(tentative),
            "excluded": len(excluded),
        },
    }


__all__ = ["build_festival_audit"]
