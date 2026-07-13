from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError

_GENERIC_FESTIVAL_THEME_TOKENS = frozenset({"festival", "festivals", "축제"})


def specific_theme_tokens(theme_pool: Sequence[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for theme in theme_pool
        if (normalized := _required_text(theme, "theme_pool").casefold())
        not in _GENERIC_FESTIVAL_THEME_TOKENS
    )


def candidate_matches_requested_theme(
    payload: Mapping[str, Any],
    requested_themes: frozenset[str],
) -> bool:
    candidate_themes = _candidate_theme_tokens(payload)
    return any(theme in requested_themes for theme in candidate_themes)


def _candidate_theme_tokens(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw_tags = payload.get("theme_tags")
    if raw_tags is None:
        return ()
    if isinstance(raw_tags, str) or not isinstance(raw_tags, Sequence):
        raise SchemaValidationError("theme_tags must be a list of strings")
    tokens: list[str] = []
    for tag in raw_tags:
        tokens.append(_required_text(tag, "theme_tags").casefold())
    return tuple(tokens)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = ["candidate_matches_requested_theme", "specific_theme_tokens"]
