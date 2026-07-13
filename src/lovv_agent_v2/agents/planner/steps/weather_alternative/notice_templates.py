from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

NoticeStrength = Literal["weak", "strong", "alternative"]

DIMENSION_PRIORITY: Final = ("rain", "heat", "cold", "snow", "low_sunshine")

_STRONG_NOTICES: Final = {
    "rain": "선택한 도시의 해당 월은 평년 기준 비가 잦은 편이라, 야외 일정은 우천 시 조정이 필요할 수 있습니다.",
    "heat": "선택한 도시의 해당 월은 평년 기준 낮 더위가 강한 편이라, 한낮 야외 일정은 무리하지 않게 조정하는 것이 좋습니다.",
    "cold": "선택한 도시의 해당 월은 평년 기준 추위가 강한 편이라, 야외 체류 시간이 긴 일정은 방한 준비가 필요합니다.",
    "snow": "선택한 도시의 해당 월은 평년 기준 눈이나 결빙 가능성이 있는 편이라, 도보 이동과 야외 일정은 조정 여지가 있습니다.",
    "low_sunshine": "선택한 도시의 해당 월은 평년 기준 일조 시간이 짧은 편이라, 전망이나 경관 중심 일정은 기대와 다를 수 있습니다.",
}

_ALTERNATIVE_NOTICES: Final = {
    "rain": "선택한 도시의 해당 월은 평년 기준 비가 잦고 야외 일정 비중이 높아, 실내 중심 대체 일정을 함께 검토할 수 있습니다.",
    "heat": "선택한 도시의 해당 월은 평년 기준 한낮 더위가 강하고 야외 일정 비중이 높아, 실내 중심 대체 일정을 함께 검토할 수 있습니다.",
    "cold": "선택한 도시의 해당 월은 평년 기준 추위가 강하고 야외 일정 비중이 높아, 실내 중심 대체 일정을 함께 검토할 수 있습니다.",
    "snow": "선택한 도시의 해당 월은 평년 기준 눈이나 결빙 가능성이 있고 야외 일정 비중이 높아, 실내 중심 대체 일정을 함께 검토할 수 있습니다.",
    "low_sunshine": "선택한 도시의 해당 월은 평년 기준 일조 시간이 짧고 야외 일정 비중이 높아, 실내 중심 대체 일정을 함께 검토할 수 있습니다.",
}


def weather_notice(dimensions: Mapping[str, str], strength: NoticeStrength) -> str:
    dimension = primary_dimension(dimensions)
    match strength:
        case "weak":
            return _weak_notice(dimension)
        case "strong":
            return _STRONG_NOTICES[dimension]
        case "alternative":
            return _ALTERNATIVE_NOTICES[dimension]


def primary_dimension(dimensions: Mapping[str, str]) -> str:
    for severity in ("high", "medium"):
        for dimension in DIMENSION_PRIORITY:
            if dimensions.get(dimension) == severity:
                return dimension
    return "rain"


def _weak_notice(dimension: str) -> str:
    return (
        _STRONG_NOTICES[dimension]
        .replace("강한 편이라", "있는 편이라")
        .replace("잦은 편이라", "있는 편이라")
    )


__all__ = ["weather_notice", "primary_dimension"]
