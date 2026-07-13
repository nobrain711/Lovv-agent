from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RESOURCE_PATH = Path(__file__).resolve().parents[4] / "resources" / "city_monthly_weather_risks.json"


@dataclass(frozen=True, slots=True)
class WeatherRiskRow:
    city_id: str
    month: int
    overall: str
    dimensions: Mapping[str, str]
    reason_codes: tuple[str, ...]


class WeatherRiskIndex:
    def __init__(self, rows: Sequence[WeatherRiskRow]) -> None:
        self._rows = {(row.city_id, row.month): row for row in rows}

    def lookup(self, city_id: str | None, month: int | None) -> WeatherRiskRow | None:
        if city_id is None or month is None:
            return None
        return self._rows.get((city_id, month))


@lru_cache(maxsize=1)
def load_default_weather_risk_index() -> WeatherRiskIndex:
    with RESOURCE_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    risks = payload.get("risks", ())
    return WeatherRiskIndex(tuple(_risk_row(item) for item in risks if isinstance(item, Mapping)))


def _risk_row(item: Mapping[str, object]) -> WeatherRiskRow:
    risk = item.get("risk")
    risk_payload = risk if isinstance(risk, Mapping) else {}
    dimensions = risk_payload.get("dimensions")
    return WeatherRiskRow(
        city_id=str(item.get("city_id", "")),
        month=int(item.get("month", 0)),
        overall=str(risk_payload.get("overall", "unknown")),
        dimensions=_string_mapping(dimensions),
        reason_codes=_string_tuple(risk_payload.get("reason_codes", ())),
    )


def _string_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


__all__ = ["WeatherRiskIndex", "WeatherRiskRow", "load_default_weather_risk_index"]
