from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from lovv_agent_v2.models.city_identity import (
    CityIdentity,
    CityIdentityMap,
    load_default_city_identity_map,
)

_CITY_SUFFIXES: Final[tuple[str, ...]] = ("시", "군", "구")
_PROVINCE_SPANS: Final[tuple[str, ...]] = ("강원도", "강원", "경상북도", "경북")
_QUALIFIED_PATTERN: Final = re.compile(r"^\s*(?P<name>[^()]+?)\s*\((?P<parent>[^()]+)\)\s*$")


@dataclass(frozen=True, slots=True)
class RegionPreferenceResolution:
    preferred_region_ids: tuple[str, ...]
    disliked_region_ids: tuple[str, ...]
    preferred_region_names: tuple[str, ...]
    disliked_region_names: tuple[str, ...]
    preferred_region_spans: tuple[str, ...]
    disliked_region_spans: tuple[str, ...]
    unresolved_region_spans: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RegionCandidate:
    span: str
    identity: CityIdentity


def resolve_region_preferences(
    *,
    preferred_spans: Sequence[str],
    disliked_spans: Sequence[str],
    raw_query: str,
) -> RegionPreferenceResolution:
    resolver = _RegionResolver(load_default_city_identity_map())
    preferred = resolver.resolve(preferred_spans, raw_query)
    disliked = resolver.resolve(disliked_spans, raw_query)
    return RegionPreferenceResolution(
        preferred_region_ids=_city_ids(preferred.resolved),
        disliked_region_ids=_city_ids(disliked.resolved),
        preferred_region_names=_city_names(preferred.resolved),
        disliked_region_names=_city_names(disliked.resolved),
        preferred_region_spans=_dedupe_text(preferred_spans),
        disliked_region_spans=_dedupe_text(disliked_spans),
        unresolved_region_spans=_dedupe_text((*preferred.unresolved, *disliked.unresolved)),
    )


@dataclass(frozen=True, slots=True)
class _ResolveResult:
    resolved: tuple[_RegionCandidate, ...]
    unresolved: tuple[str, ...]


class _RegionResolver:
    def __init__(self, city_map: CityIdentityMap) -> None:
        self._city_map = city_map
        self._identities = city_map.identities()

    def resolve(self, spans: Sequence[str], raw_query: str) -> _ResolveResult:
        resolved: list[_RegionCandidate] = []
        unresolved: list[str] = []
        for span in _dedupe_text(spans):
            identity = self._resolve_one(span, raw_query)
            if identity is None:
                unresolved.append(span)
                continue
            resolved.append(_RegionCandidate(span=span, identity=identity))
        return _ResolveResult(resolved=tuple(resolved), unresolved=tuple(unresolved))

    def _resolve_one(self, span: str, raw_query: str) -> CityIdentity | None:
        exact = self._city_map.get(span)
        if exact is not None and not self._has_ambiguous_local_name(span):
            return exact
        qualified = _qualified_parts(span)
        if qualified is not None:
            return self._unique_match(name=qualified["name"], parent=qualified["parent"])
        normalized = _normalize_span(span)
        direct = self._unique_match(name=normalized, parent=None)
        if direct is not None:
            return direct
        parent = _parent_context(raw_query, self._identities)
        if parent is None:
            return None
        return self._unique_match(name=normalized, parent=parent)

    def _has_ambiguous_local_name(self, span: str) -> bool:
        normalized = _normalize_span(span)
        if not normalized.endswith("구"):
            return False
        matches = tuple(
            identity
            for identity in self._identities
            if normalized in _aliases(identity)
        )
        return len(matches) > 1

    def _unique_match(self, *, name: str, parent: str | None) -> CityIdentity | None:
        matches = tuple(
            identity
            for identity in self._identities
            if _identity_matches(identity, name=name, parent=parent)
        )
        if len(matches) != 1:
            return None
        return matches[0]


def extract_region_spans(raw_query: str) -> tuple[str, ...]:
    city_map = load_default_city_identity_map()
    matches: list[tuple[int, int, str]] = []
    for identity in city_map.identities():
        for alias in _aliases(identity):
            if len(alias) < 2:
                continue
            start = raw_query.find(alias)
            if start >= 0:
                matches.append((start, -len(alias), alias))
    for span in _PROVINCE_SPANS:
        start = raw_query.find(span)
        if start >= 0:
            matches.append((start, -len(span), span))
    spans: list[str] = []
    covered: set[int] = set()
    for start, negative_length, alias in sorted(matches):
        positions = set(range(start, start - negative_length))
        if covered.intersection(positions):
            continue
        covered.update(positions)
        spans.append(alias)
    return _dedupe_text(spans)


def _identity_matches(identity: CityIdentity, *, name: str, parent: str | None) -> bool:
    if parent is not None and not _parent_matches(identity, parent):
        return False
    return name in _aliases(identity)


def _aliases(identity: CityIdentity) -> tuple[str, ...]:
    city_name = identity.city_name_ko or ""
    base = _base_city_name(city_name)
    aliases = [city_name, base]
    if not base.endswith(_CITY_SUFFIXES):
        for suffix in _CITY_SUFFIXES:
            aliases.append(f"{base}{suffix}")
    if identity.province is not None:
        province_aliases = _province_aliases(identity.province)
        aliases.extend(f"{province} {base}" for province in province_aliases)
        aliases.extend(f"{base} ({province})" for province in province_aliases)
    return _dedupe_text(aliases)


def _qualified_parts(span: str) -> Mapping[str, str] | None:
    match = _QUALIFIED_PATTERN.match(span)
    if match is None:
        return None
    return {
        "name": _normalize_span(match.group("name")),
        "parent": _normalize_span(match.group("parent")),
    }


def _identity_parent_aliases(identity: CityIdentity) -> tuple[str, ...]:
    if identity.province is None:
        return ()
    return _province_aliases(identity.province)


def _parent_matches(identity: CityIdentity, parent: str) -> bool:
    normalized_parent = _normalize_span(parent)
    return normalized_parent in _identity_parent_aliases(identity)


def _parent_context(raw_query: str, identities: Sequence[CityIdentity]) -> str | None:
    parents = tuple(
        province
        for identity in identities
        for province in _identity_parent_aliases(identity)
        if province in raw_query
    )
    unique = _dedupe_text(parents)
    if len(unique) != 1:
        return None
    return unique[0]


def _province_aliases(province: str) -> tuple[str, ...]:
    normalized = _normalize_span(province)
    aliases = [normalized]
    for suffix in ("특별자치도", "광역시", "특별시", "도"):
        if normalized.endswith(suffix):
            aliases.append(normalized[: -len(suffix)])
    if normalized == "경상북도":
        aliases.append("경북")
    if normalized == "강원특별자치도":
        aliases.extend(("강원", "강원도"))
    return _dedupe_text(aliases)


def _base_city_name(city_name: str) -> str:
    name = _normalize_span(city_name)
    qualified = _qualified_parts(name)
    if qualified is not None:
        return qualified["name"]
    for suffix in _CITY_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _normalize_span(value: str) -> str:
    return " ".join(value.strip().split())


def _city_ids(candidates: Sequence[_RegionCandidate]) -> tuple[str, ...]:
    return _dedupe_text(candidate.identity.city_id for candidate in candidates)


def _city_names(candidates: Sequence[_RegionCandidate]) -> tuple[str, ...]:
    return _dedupe_text(
        candidate.identity.city_name_ko
        for candidate in candidates
        if candidate.identity.city_name_ko is not None
    )


def _dedupe_text(values: Sequence[str] | Sequence[str | None]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        normalized = _normalize_span(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


__all__ = [
    "RegionPreferenceResolution",
    "extract_region_spans",
    "resolve_region_preferences",
]
