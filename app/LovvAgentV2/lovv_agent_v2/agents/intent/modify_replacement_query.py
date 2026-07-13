from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

_GENERIC_REPLACEMENT_PHRASES: Final = (
    "다른 곳",
    "다른 장소",
    "다른 코스",
    "비슷한 곳",
    "비슷한 장소",
    "근처 다른 곳",
)


def replacement_query_fields(raw_phrase: str | None) -> dict[str, str | bool | None]:
    raw_query = normalized_replacement_phrase(raw_phrase)
    return {
        "replacement_query": hyde_replacement_query(raw_query),
        "replacement_query_raw": raw_query,
        "query_required": raw_query is not None,
    }


def normalized_replacement_phrase(raw_phrase: str | None) -> str | None:
    if raw_phrase is None:
        return None
    normalized = raw_phrase.strip(" .,。")
    if not normalized or normalized in _GENERIC_REPLACEMENT_PHRASES:
        return None
    return normalized


def hyde_replacement_query(raw_phrase: str | None) -> str | None:
    normalized = normalized_replacement_phrase(raw_phrase)
    if normalized is None:
        return None
    if normalized.endswith(("장소.", "공간.", "곳.")):
        return normalized
    if any(keyword in normalized for keyword in ("전시", "미술관", "갤러리", "실내")):
        return "차분하게 머물며 작품과 전시를 감상할 수 있는 실내 문화 공간."
    if any(keyword in normalized for keyword in ("바다", "해안", "해변", "전망")):
        return "탁 트인 바다 전망을 감상할 수 있는 해안 장소."
    if any(keyword in normalized for keyword in ("숲", "산책", "자연", "트레킹")):
        return "조용하고 한적한 숲길을 천천히 걸을 수 있는 자연 산책 장소."
    if any(keyword in normalized for keyword in ("온천", "휴양", "힐링", "쉬")):
        return "따뜻하고 평온한 분위기에서 조용히 휴식할 수 있는 장소."
    return f"{normalized} 분위기와 장소 유형이 잘 드러나는 방문지."


def slot_replacement_phrase(
    raw_query: str,
    item: Mapping[str, object],
    *,
    order_token_re: str,
) -> str | None:
    if "말고" in raw_query:
        _, replacement = raw_query.split("말고", 1)
        normalized = _strip_replace_suffix(replacement)
    else:
        normalized = _strip_replace_suffix(_strip_target_prefix(raw_query, item, order_token_re))
    if normalized in {"다른 곳", "다른 장소", "다른 코스"}:
        return None
    return normalized or None


def _strip_target_prefix(
    raw_query: str,
    item: Mapping[str, object],
    order_token_re: str,
) -> str:
    normalized = re.sub(
        rf"^\s*\d+일차\s*(오전|오후|{order_token_re})?\s*(장소|코스|일정)?\s*(은|는|을|를|만)?\s*",
        "",
        raw_query,
    )
    title = _optional_text(item.get("title", item.get("name")))
    if title is None:
        return normalized
    return re.sub(rf"^\s*{re.escape(title)}\s*(은|는|을|를|만)?\s*", "", normalized)


def _strip_replace_suffix(value: str) -> str:
    return re.sub(
        r"(쪽으로|으로|로)?\s*(바꾸고|바꿔줘|바꿔|변경해줘|교체해줘)\.?$",
        "",
        value.strip(" .,。"),
    ).strip(" .,。")


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "hyde_replacement_query",
    "normalized_replacement_phrase",
    "replacement_query_fields",
    "slot_replacement_phrase",
]
