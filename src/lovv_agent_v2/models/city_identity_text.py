from __future__ import annotations

from collections.abc import Sequence

from lovv_agent_v2.models.city_identity import CityIdentity, CityIdentityMap


def find_city_identity_in_text(
    city_map: CityIdentityMap,
    text: str,
) -> CityIdentity | None:
    for identity in sorted(city_map.identities(), key=_identity_name_length, reverse=True):
        name = identity.city_name_ko
        if name is not None and name in text:
            return identity
    aliases = _unique_city_aliases(city_map.identities())
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in text:
            return aliases[alias]
    return None


def _identity_name_length(identity: CityIdentity) -> int:
    return len(identity.city_name_ko or "")


def _unique_city_aliases(identities: Sequence[CityIdentity]) -> dict[str, CityIdentity]:
    alias_map: dict[str, CityIdentity] = {}
    duplicates: set[str] = set()
    for identity in identities:
        alias = _city_name_alias(identity.city_name_ko)
        if alias is None:
            continue
        if alias in alias_map and alias_map[alias].city_id != identity.city_id:
            duplicates.add(alias)
            continue
        alias_map[alias] = identity
    return {alias: identity for alias, identity in alias_map.items() if alias not in duplicates}


def _city_name_alias(name: str | None) -> str | None:
    if name is None or "(" in name:
        return None
    if name.endswith(("시", "군", "구")) and len(name) > 1:
        return name[:-1]
    return None


__all__ = ["find_city_identity_in_text"]
