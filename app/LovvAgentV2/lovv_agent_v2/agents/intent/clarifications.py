from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from lovv_agent_v2.models.clarification_texts import clarification_helper_text

PREFERENCE_CLARIFYING_QUESTION: Final = (
    "선호와 비선호가 동시에 언급된 테마나 지역이 있어 우선순위를 확인해야 합니다."
)
SUPPORTED_COUNTRY: Final = "KR"
UNSUPPORTED_REGION_PROMPT: Final = (
    "현재는 국내 여행지만 추천할 수 있습니다. 국내 지역으로 다시 입력해 주세요."
)
_UNSUPPORTED_DESTINATION_MARKERS: Final = (
    "일본",
    "도쿄",
    "오사카",
    "교토",
    "후쿠오카",
    "japan",
    "tokyo",
    "osaka",
    "kyoto",
    "fukuoka",
)


def set_contradiction_clarification(intent: dict[str, Any]) -> None:
    reasons = _text_tuple(intent.get("contradiction_reasons", ()))
    if not reasons:
        return
    intent["clarification"] = {
        "reason_code": "contradiction",
        "prompt": PREFERENCE_CLARIFYING_QUESTION,
        "options": [
            {
                "option_id": "revise_conditions",
                "label": "조건 다시 입력",
                "helper_text": clarification_helper_text(
                    "contradiction",
                    "revise_conditions",
                    "충돌하는 선호/비선호 조건을 정리해 다시 입력합니다.",
                ),
                "apply": {},
                "then": "abort",
            },
        ],
        "context": {"contradiction_reasons": list(reasons)},
        "failure_signals": list(reasons),
    }


def set_unsupported_region_clarification(
    intent: dict[str, Any],
    request: Mapping[str, Any] | None,
    city_input: Mapping[str, Any],
) -> None:
    reason = _unsupported_region_reason(request, city_input)
    if reason is None:
        return
    intent["needs_clarification"] = True
    intent["clarifying_question"] = UNSUPPORTED_REGION_PROMPT
    intent["clarification"] = {
        "reason_code": "unsupported_region",
        "prompt": UNSUPPORTED_REGION_PROMPT,
        "options": [
            {
                "option_id": "revise_conditions",
                "label": "국내 여행지로 다시 입력",
                "helper_text": clarification_helper_text(
                    "unsupported_region",
                    "revise_conditions",
                    "현재 지원 범위인 국내 여행지로 조건을 다시 입력합니다.",
                ),
                "apply": {},
                "then": "abort",
            },
        ],
        "context": {"reason": reason},
        "failure_signals": [reason],
    }


def _unsupported_region_reason(
    request: Mapping[str, Any] | None,
    city_input: Mapping[str, Any],
) -> str | None:
    country = _text(city_input.get("country"))
    if country is not None and country.upper() != SUPPORTED_COUNTRY:
        return f"country:{country.upper()}"
    raw_query = _raw_query(request)
    if raw_query is not None and _has_unsupported_destination_marker(raw_query):
        return "destination:unsupported_region"
    return None


def _raw_query(request: Mapping[str, Any] | None) -> str | None:
    if request is None:
        return None
    for key in ("raw_query", "rawQuery", "naturalLanguageQuery"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _has_unsupported_destination_marker(raw_query: str) -> bool:
    normalized = raw_query.lower()
    return any(marker in normalized for marker in _UNSUPPORTED_DESTINATION_MARKERS)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


__all__ = [
    "PREFERENCE_CLARIFYING_QUESTION",
    "set_contradiction_clarification",
    "set_unsupported_region_clarification",
]
