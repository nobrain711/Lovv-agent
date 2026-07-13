from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, assert_never

from lovv_agent_v2.agents.intent.region_resolver import (
    extract_region_spans,
    resolve_region_preferences,
)
from lovv_agent_v2.agents.intent.validator import validate_preference_sets

PreferencePolarity = Literal["preferred", "disliked"]

THEME_ID_TO_LABEL: Final[dict[str, str]] = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
    "food_local": "미식·노포",
}

_THEME_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "sea_coast": ("바다", "해안", "해변", "바닷가", "오션", "섬"),
    "nature_trekking": ("자연", "트레킹", "등산", "숲길", "숲"),
    "history_tradition": ("역사", "전통", "유적", "문화재", "고택", "한옥"),
    "art_sense": ("예술", "감성", "전시", "미술관", "갤러리", "공방"),
    "healing_rest": ("온천", "휴양", "힐링", "스파", "쉼", "쉬는"),
    "food_local": ("미식", "맛집", "노포", "로컬 맛", "음식", "먹거리"),
}

_NEGATIVE_SEPARATORS: Final[tuple[str, ...]] = (
    "제외하고",
    "피하고",
    "별로고",
    "빼고",
    "빼줘",
    "빼",
    "말고",
)
_CONTRAST_SEPARATORS: Final[tuple[str, ...]] = (
    "하지만",
    "그렇지만",
    "그러나",
    "근데",
    "는데",
    "은데",
    "지만",
)
_NEGATIVE_MARKERS: Final[tuple[str, ...]] = (
    "싫",
    "피하",
    "원하지",
    "별로",
    "제외",
    "빼",
    "말고",
    "안 가",
)


@dataclass(frozen=True, slots=True)
class IntentPreferenceResult:
    cleaned_raw_query: str
    preferred_theme_ids: tuple[str, ...] = ()
    disliked_theme_ids: tuple[str, ...] = ()
    preferred_region_ids: tuple[str, ...] = ()
    disliked_region_ids: tuple[str, ...] = ()
    preferred_region_spans: tuple[str, ...] = ()
    disliked_region_spans: tuple[str, ...] = ()
    unresolved_region_spans: tuple[str, ...] = ()
    preferred_region_names_value: tuple[str, ...] = ()
    disliked_region_names_value: tuple[str, ...] = ()
    contradiction_reasons: tuple[str, ...] = ()

    @property
    def active_theme_labels(self) -> tuple[str, ...]:
        return tuple(THEME_ID_TO_LABEL[theme_id] for theme_id in self.preferred_theme_ids)

    @property
    def preferred_region_names(self) -> tuple[str, ...]:
        return self.preferred_region_names_value

    @property
    def disliked_region_names(self) -> tuple[str, ...]:
        return self.disliked_region_names_value

    @property
    def needs_clarification(self) -> bool:
        return bool(self.contradiction_reasons)

    @property
    def clarifying_question(self) -> str | None:
        if not self.needs_clarification:
            return None
        return "선호와 비선호가 동시에 언급된 테마나 지역이 있어 우선순위를 확인해야 합니다."


@dataclass(frozen=True, slots=True)
class _PolarizedSegment:
    text: str
    polarity: PreferencePolarity


def parse_initial_query(raw_query: str) -> IntentPreferenceResult:
    normalized_query = " ".join(raw_query.split())
    preferred_theme_ids, disliked_theme_ids = _extract_preferences(
        normalized_query,
        _THEME_KEYWORDS,
    )
    preferred_region_spans, disliked_region_spans = _extract_preferences(
        normalized_query,
        _region_keyword_map(normalized_query),
    )
    region_resolution = resolve_region_preferences(
        preferred_spans=preferred_region_spans,
        disliked_spans=disliked_region_spans,
        raw_query=normalized_query,
    )
    validation = validate_preference_sets(
        preferred_theme_ids=preferred_theme_ids,
        disliked_theme_ids=disliked_theme_ids,
        preferred_region_ids=region_resolution.preferred_region_ids,
        disliked_region_ids=region_resolution.disliked_region_ids,
    )
    return IntentPreferenceResult(
        cleaned_raw_query=clean_preference_query(normalized_query),
        preferred_theme_ids=preferred_theme_ids,
        disliked_theme_ids=disliked_theme_ids,
        preferred_region_ids=region_resolution.preferred_region_ids,
        disliked_region_ids=region_resolution.disliked_region_ids,
        preferred_region_spans=region_resolution.preferred_region_spans,
        disliked_region_spans=region_resolution.disliked_region_spans,
        unresolved_region_spans=region_resolution.unresolved_region_spans,
        preferred_region_names_value=region_resolution.preferred_region_names,
        disliked_region_names_value=region_resolution.disliked_region_names,
        contradiction_reasons=validation.contradiction_reasons,
    )


def theme_labels(theme_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(THEME_ID_TO_LABEL[theme_id] for theme_id in theme_ids)


def region_names(region_ids: tuple[str, ...]) -> tuple[str, ...]:
    resolution = resolve_region_preferences(
        preferred_spans=region_ids,
        disliked_spans=(),
        raw_query=" ".join(region_ids),
    )
    return resolution.preferred_region_names


def clean_preference_query(raw_query: str) -> str:
    normalized_query = " ".join(raw_query.split())
    positive_segments = tuple(
        segment.text.strip(" ,.!?。")
        for segment in _polarized_segments(normalized_query)
        if segment.polarity == "preferred" and segment.text.strip(" ,.!?。")
    )
    return " ".join(positive_segments) if positive_segments else normalized_query


def _extract_preferences(
    text: str,
    keyword_map: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    preferred_ids: list[str] = []
    disliked_ids: list[str] = []
    for segment in _polarized_segments(text):
        matched_ids = _matching_ids(segment.text, keyword_map)
        match segment.polarity:
            case "preferred":
                preferred_ids.extend(matched_ids)
            case "disliked":
                disliked_ids.extend(matched_ids)
            case unreachable:
                assert_never(unreachable)
    return _dedupe(preferred_ids), _dedupe(disliked_ids)


def _region_keyword_map(raw_query: str) -> dict[str, tuple[str, ...]]:
    return {span: (span,) for span in extract_region_spans(raw_query)}


def _polarized_segments(text: str) -> tuple[_PolarizedSegment, ...]:
    sentence_parts = tuple(part.strip() for part in re.split(r"[.!?。]+", text))
    if len(tuple(part for part in sentence_parts if part)) > 1:
        return tuple(
            segment
            for part in sentence_parts
            if part
            for segment in _polarized_segments(part)
        )

    for separator in _CONTRAST_SEPARATORS:
        if separator in text:
            segments: list[_PolarizedSegment] = []
            for part in text.split(separator):
                segments.extend(_polarized_segments(part))
            return tuple(segments)

    for separator in _NEGATIVE_SEPARATORS:
        if separator in text:
            left, right = text.split(separator, 1)
            segments = []
            if left.strip():
                segments.append(_PolarizedSegment(text=left, polarity="disliked"))
            if right.strip():
                segments.append(_PolarizedSegment(text=right, polarity="preferred"))
            return tuple(segments)

    polarity: PreferencePolarity = "disliked" if _has_negative_marker(text) else "preferred"
    return (_PolarizedSegment(text=text, polarity=polarity),)


def _has_negative_marker(text: str) -> bool:
    return any(marker in text for marker in _NEGATIVE_MARKERS)


def _matching_ids(
    text: str,
    keyword_map: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    return tuple(
        item_id
        for item_id, keywords in keyword_map.items()
        if any(keyword in text for keyword in keywords)
    )


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
