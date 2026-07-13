from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.agents.festival_verifier.gate_result import FestivalStatusCandidate


def verified_city_payloads(
    candidates: Sequence[FestivalStatusCandidate],
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        city = grouped.setdefault(
            candidate.city_id,
            {
                "ddb_pk": _city_ddb_pk(candidate.payload, candidate.city_id),
                "city_id": candidate.city_id,
                "city_name": candidate.city_name,
                "festivals": [],
            },
        )
        city["festivals"].append(candidate.payload)
    return tuple(grouped.values())


def unique_city_ids(candidates: Sequence[FestivalStatusCandidate]) -> tuple[str, ...]:
    seen: set[str] = set()
    city_ids: list[str] = []
    for candidate in candidates:
        if candidate.city_id in seen:
            continue
        seen.add(candidate.city_id)
        city_ids.append(candidate.city_id)
    return tuple(city_ids)


def _city_ddb_pk(payload: Mapping[str, Any], city_id: str) -> str:
    for key in ("ddb_pk", "city_key", "PK", "pk"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"CITY#{city_id}"


__all__ = ["unique_city_ids", "verified_city_payloads"]
