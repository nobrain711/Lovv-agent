from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

RESOURCE_PATH: Final = Path(__file__).resolve().parents[1] / "resources" / "clarification_option_texts.json"


@dataclass(frozen=True, slots=True)
class ClarificationOptionText:
    label: str | None = None
    helper_text: str | None = None


def clarification_prompt_text(reason_code: str, default: str) -> str:
    prompt = _prompt_texts().get(reason_code)
    return prompt if prompt is not None else default


def clarification_label_text(
    reason_code: str,
    option_id: str,
    default: str,
) -> str:
    option_text = _option_text(reason_code, option_id)
    if option_text is None or option_text.label is None:
        return default
    return option_text.label


def clarification_helper_text(
    reason_code: str,
    option_id: str,
    default: str,
) -> str:
    option_text = _option_text(reason_code, option_id)
    if option_text is None or option_text.helper_text is None:
        return default
    return option_text.helper_text


def _option_text(reason_code: str, option_id: str) -> ClarificationOptionText | None:
    reason_texts = _option_texts().get(reason_code)
    if reason_texts is None:
        return None
    return reason_texts.get(option_id) or reason_texts.get(_wildcard_key(option_id))


@lru_cache(maxsize=1)
def _option_texts() -> Mapping[str, Mapping[str, ClarificationOptionText]]:
    payload = _resource_payload()
    return {
        str(reason): _option_text_map(options)
        for reason, options in payload.items()
        if isinstance(options, Mapping)
    }


@lru_cache(maxsize=1)
def _prompt_texts() -> Mapping[str, str]:
    prompts: dict[str, str] = {}
    for reason, options in _resource_payload().items():
        if not isinstance(options, Mapping):
            continue
        prompt = _string_or_none(options.get("_prompt"))
        if prompt is not None:
            prompts[str(reason)] = prompt
    return prompts


@lru_cache(maxsize=1)
def _resource_payload() -> Mapping[Any, Any]:
    with RESOURCE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, Mapping) else {}


def _option_text_map(payload: Mapping[Any, Any]) -> Mapping[str, ClarificationOptionText]:
    option_texts: dict[str, ClarificationOptionText] = {}
    for key, value in payload.items():
        option_text = _option_text_from_value(value)
        if option_text is not None:
            option_texts[str(key)] = option_text
    return option_texts


def _option_text_from_value(value: Any) -> ClarificationOptionText | None:
    if isinstance(value, str) and value.strip():
        return ClarificationOptionText(helper_text=value)
    if not isinstance(value, Mapping):
        return None
    label = _string_or_none(value.get("label"))
    helper_text = _string_or_none(value.get("helperText", value.get("helper_text")))
    if label is None and helper_text is None:
        return None
    return ClarificationOptionText(label=label, helper_text=helper_text)


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _wildcard_key(option_id: str) -> str:
    prefix, separator, _ = option_id.partition(":")
    return f"{prefix}:*" if separator else option_id


__all__ = [
    "clarification_helper_text",
    "clarification_label_text",
    "clarification_prompt_text",
]
