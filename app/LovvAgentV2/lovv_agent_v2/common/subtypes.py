from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

SUBTYPE_RESOURCE = Path(__file__).resolve().parents[1] / "resources" / "attraction_subtypes.json"


@dataclass(frozen=True, slots=True)
class AttractionSubtype:
    code: str
    name: str
    large_category: str
    middle_category: str
    theme: str


@cache
def attraction_subtypes() -> dict[str, AttractionSubtype]:
    raw = json.loads(SUBTYPE_RESOURCE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    subtypes: dict[str, AttractionSubtype] = {}
    for code, value in raw.items():
        if not isinstance(code, str) or not isinstance(value, dict):
            continue
        subtypes[code] = AttractionSubtype(
            code=code,
            name=_text(value.get("name")),
            large_category=_text(value.get("large_category")),
            middle_category=_text(value.get("middle_category")),
            theme=_text(value.get("theme")),
        )
    return subtypes


def subtype_for_code(code: str | None) -> AttractionSubtype | None:
    if not code:
        return None
    return attraction_subtypes().get(code)


def subtype_name(code: str | None) -> str:
    subtype = subtype_for_code(code)
    return subtype.name if subtype else ""


def subtype_label(code: str | None) -> str:
    subtype = subtype_for_code(code)
    if subtype is None:
        return code or ""
    return " > ".join(part for part in (subtype.large_category, subtype.middle_category, subtype.name) if part)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
