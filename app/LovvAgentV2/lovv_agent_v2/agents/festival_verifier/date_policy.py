from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError

DATE_STATUSES: tuple[str, ...] = (
    "confirmed",
    "tentative",
    "outdated",
    "unknown",
    "skipped",
)


@dataclass(frozen=True, slots=True)
class FestivalMonthPoint:
    year: int | None
    month: int


def derive_date_status(
    payload: Mapping[str, Any],
    *,
    travel_month: int,
    target_year: int | None,
) -> str:
    explicit_status = _optional_text(payload.get("date_status"))
    match explicit_status:
        case "tentative" | "outdated" | "unknown" | "skipped":
            return explicit_status
        case "confirmed" | None:
            return _derive_from_month_window(
                payload,
                travel_month=travel_month,
                target_year=target_year,
            )
        case unreachable:
            raise SchemaValidationError(f"unsupported festival date_status: {unreachable}")


def candidate_matches_month(payload: Mapping[str, Any], travel_month: int) -> bool:
    month = payload.get("month")
    if month is None:
        return True
    return month_number(month) == travel_month


def month_number(value: Any) -> int:
    parsed = _positive_int(value, "travel_month")
    if parsed > 12:
        raise SchemaValidationError("travel_month must be between 1 and 12")
    return parsed


def positive_int(value: Any, field_name: str) -> int:
    return _positive_int(value, field_name)


def _derive_from_month_window(
    payload: Mapping[str, Any],
    *,
    travel_month: int,
    target_year: int | None,
) -> str:
    start_month = _month_point_from_value(
        _first_optional(payload, "event_start_date", "start_date"),
    )
    end_month = _month_point_from_value(
        _first_optional(payload, "event_end_date", "end_date"),
    )
    date_point = start_month or end_month
    explicit_year = _year_from_value(
        _first_optional(payload, "event_year", "festival_year", "year"),
    )
    data_year = (
        start_month.year
        if start_month is not None and start_month.year is not None
        else explicit_year
    )
    if data_year is None and end_month is not None:
        data_year = end_month.year
    if not candidate_matches_month(payload, travel_month):
        return "skipped"
    if "month" not in payload and date_point is not None and date_point.month != travel_month:
        return "skipped"
    if target_year is not None and data_year is not None and data_year != target_year:
        return "outdated"
    return "confirmed"


def _month_point_from_value(value: Any) -> FestivalMonthPoint | None:
    if value is None:
        return None
    if isinstance(value, date):
        return FestivalMonthPoint(year=value.year, month=value.month)
    if isinstance(value, int) and 1 <= value <= 12:
        return FestivalMonthPoint(year=None, month=value)
    if not isinstance(value, str):
        raise SchemaValidationError("festival date must be a string")
    text = value.strip()
    if not text:
        return None
    parts = re.findall(r"\d+", text)
    if len(parts) >= 3:
        return FestivalMonthPoint(year=int(parts[0]), month=int(parts[1]))
    if len(parts) >= 2:
        return FestivalMonthPoint(year=int(parts[0]), month=int(parts[1]))
    if len(parts) == 1 and len(parts[0]) in {6, 8}:
        compact = parts[0]
        return FestivalMonthPoint(year=int(compact[:4]), month=int(compact[4:6]))
    if len(parts) == 1 and len(parts[0]) <= 2:
        return FestivalMonthPoint(year=None, month=month_number(int(parts[0])))
    raise SchemaValidationError("festival date must include a month")


def _year_from_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and value > 999:
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = re.search(r"\d{4}", text)
        if match is not None:
            return int(match.group(0))
    point = _month_point_from_value(value)
    return None if point is None else point.year


def _first_optional(record: Mapping[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError("optional_text must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError("optional_text must be a non-empty string")
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError as exc:
            raise SchemaValidationError(f"{field_name} must be an integer") from exc
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1:
        raise SchemaValidationError(f"{field_name} must be positive")
    return value


__all__ = [
    "DATE_STATUSES",
    "candidate_matches_month",
    "derive_date_status",
    "month_number",
    "positive_int",
]
