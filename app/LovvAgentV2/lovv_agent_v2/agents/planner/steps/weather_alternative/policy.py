from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lovv_agent_v2.agents.planner.steps.weather_alternative.notice_templates import (
    weather_notice,
)
from lovv_agent_v2.agents.planner.steps.weather_alternative.resource import WeatherRiskRow

WeatherDecisionStatus = Literal[
    "unavailable",
    "low",
    "unknown_exposure",
    "notice",
    "alternative_available",
]
WeatherNoticeLevel = Literal["none", "weak", "strong"]


@dataclass(frozen=True, slots=True)
class WeatherDecisionPolicy:
    medium_notice_ratio: float = 0.40
    high_notice_ratio: float = 0.25
    high_alternative_ratio: float = 0.50


@dataclass(frozen=True, slots=True)
class WeatherDecision:
    status: WeatherDecisionStatus
    notice_level: WeatherNoticeLevel
    should_offer_alternative: bool
    notice: str | None
    weather_sensitive_ratio: float | None

    def audit(self, risk: WeatherRiskRow | None, known_count: int, sensitive_count: int) -> dict[str, object]:
        return {
            "status": self.status,
            "overall": risk.overall if risk is not None else None,
            "risk_dimensions": dict(risk.dimensions) if risk is not None else {},
            "reason_codes": risk.reason_codes if risk is not None else (),
            "notice_level": self.notice_level,
            "should_offer_alternative": self.should_offer_alternative,
            "known_item_count": known_count,
            "weather_sensitive_item_count": sensitive_count,
            "weather_sensitive_ratio": self.weather_sensitive_ratio,
        }


def decide_weather(
    risk: WeatherRiskRow | None,
    *,
    known_count: int,
    sensitive_count: int,
    policy: WeatherDecisionPolicy,
) -> WeatherDecision:
    if risk is None:
        return _decision("unavailable", "none", False, None, None)
    if known_count == 0:
        return _decision("unknown_exposure", "none", False, None, None)
    ratio = sensitive_count / known_count
    match risk.overall:
        case "low":
            return _decision("low", "none", False, None, ratio)
        case "medium":
            return _medium_decision(risk, ratio, policy)
        case "high":
            return _high_decision(risk, ratio, policy)
        case _:
            return _decision("unavailable", "none", False, None, ratio)


def _medium_decision(
    risk: WeatherRiskRow,
    ratio: float,
    policy: WeatherDecisionPolicy,
) -> WeatherDecision:
    if ratio < policy.medium_notice_ratio:
        return _decision("low", "none", False, None, ratio)
    return _decision(
        "notice",
        "weak",
        False,
        weather_notice(risk.dimensions, "weak"),
        ratio,
    )


def _high_decision(
    risk: WeatherRiskRow,
    ratio: float,
    policy: WeatherDecisionPolicy,
) -> WeatherDecision:
    if ratio >= policy.high_alternative_ratio:
        return _decision(
            "alternative_available",
            "strong",
            True,
            weather_notice(risk.dimensions, "alternative"),
            ratio,
        )
    if ratio >= policy.high_notice_ratio:
        return _decision(
            "notice",
            "strong",
            False,
            weather_notice(risk.dimensions, "strong"),
            ratio,
        )
    return _decision("low", "none", False, None, ratio)


def _decision(
    status: WeatherDecisionStatus,
    notice_level: WeatherNoticeLevel,
    should_offer_alternative: bool,
    notice: str | None,
    ratio: float | None,
) -> WeatherDecision:
    return WeatherDecision(
        status=status,
        notice_level=notice_level,
        should_offer_alternative=should_offer_alternative,
        notice=notice,
        weather_sensitive_ratio=ratio,
    )


__all__ = ["WeatherDecision", "WeatherDecisionPolicy", "decide_weather"]
