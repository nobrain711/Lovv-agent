from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from lovv_agent_v2.models.schemas import SchemaValidationError

DEFAULT_CITY_METADATA_PATH = Path(
    "metadata_audit/kr-tour-domain-v2-all-metadata-20260630T001340Z.json",
)
DEFAULT_CITY_IDENTITY_MAP_PATH = (
    Path(__file__).resolve().parents[1] / "resources" / "city_identity_map.json"
)


@dataclass(frozen=True, slots=True)
class CityIdentity:
    city_id: str
    ddb_pk: str
    city_name_ko: str | None = None
    city_name_en: str | None = None
    province: str | None = None
    country: str = "KR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "city_id": self.city_id,
            "ddb_pk": self.ddb_pk,
            "city_key": self.ddb_pk,
            "city_name_ko": self.city_name_ko,
            "city_name_en": self.city_name_en,
            "province": self.province,
            "country": self.country,
        }


class CityIdentityMap:
    def __init__(self, identities: Sequence[CityIdentity]) -> None:
        self._by_key: dict[str, CityIdentity] = {}
        for identity in identities:
            self._register(identity)

    def get(self, value: Any) -> CityIdentity | None:
        if not isinstance(value, str):
            return None
        return self._by_key.get(_lookup_key(value))

    def require(self, value: Any) -> CityIdentity:
        identity = self.get(value)
        if identity is None:
            raise SchemaValidationError("unknown city identity")
        return identity

    def identities(self) -> tuple[CityIdentity, ...]:
        seen: set[str] = set()
        result: list[CityIdentity] = []
        for identity in self._by_key.values():
            if identity.city_id in seen:
                continue
            seen.add(identity.city_id)
            result.append(identity)
        return tuple(result)

    def _register(self, identity: CityIdentity) -> None:
        for value in (
            identity.city_id,
            identity.ddb_pk,
            identity.city_name_ko,
            identity.city_name_en,
        ):
            if isinstance(value, str) and value.strip():
                self._by_key.setdefault(_lookup_key(value), identity)


def load_default_city_identity_map() -> CityIdentityMap:
    path = Path(
        os.environ.get("LOVV_CITY_IDENTITY_MAP_PATH", DEFAULT_CITY_IDENTITY_MAP_PATH),
    )
    return _load_city_identity_map_cached(str(path))


def load_city_identity_map(path: Path) -> CityIdentityMap:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SchemaValidationError("city identity map must contain an object")
    cities = payload.get("cities")
    if not isinstance(cities, list):
        raise SchemaValidationError("city identity map must contain cities")
    return CityIdentityMap(_compact_city_identities(cities))


def build_city_identity_map_from_metadata(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SchemaValidationError("city metadata file must contain an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise SchemaValidationError("city metadata file must contain records")
    identities = _metadata_city_identities(records)
    return {
        "source": str(path).replace("\\", "/"),
        "generated_from": payload.get("generated_at_utc"),
        "record_count": payload.get("record_count"),
        "city_count": len(identities),
        "cities": [identity.to_dict() for identity in identities],
    }


def enrich_city_select_identity(
    city_select_input: Mapping[str, Any],
    *,
    city_map: CityIdentityMap | None = None,
) -> dict[str, Any]:
    enriched = dict(city_select_input)
    if not _has_identity_hint(enriched):
        return enriched
    identity = _identity_for_city_select(enriched, city_map or load_default_city_identity_map())
    if identity is None:
        return enriched
    enriched.setdefault("destination_id", identity.city_id)
    enriched["city_key"] = identity.ddb_pk
    enriched["ddb_pk"] = identity.ddb_pk
    if identity.city_name_ko is not None:
        enriched["destination_label"] = identity.city_name_ko
    if identity.city_name_en is not None:
        enriched["city_name_en"] = identity.city_name_en
    if identity.province is not None:
        enriched["province"] = identity.province
    return enriched


@lru_cache(maxsize=4)
def _load_city_identity_map_cached(path: str) -> CityIdentityMap:
    return load_city_identity_map(Path(path))


def _compact_city_identities(cities: Sequence[Any]) -> tuple[CityIdentity, ...]:
    identities: list[CityIdentity] = []
    for city in cities:
        if not isinstance(city, Mapping):
            continue
        city_id = _optional_text(city.get("city_id"))
        ddb_pk = _optional_text(city.get("ddb_pk")) or _optional_text(city.get("city_key"))
        if city_id is None or ddb_pk is None:
            continue
        identities.append(
            CityIdentity(
                city_id=city_id,
                ddb_pk=ddb_pk,
                city_name_ko=_optional_text(city.get("city_name_ko")),
                city_name_en=_optional_text(city.get("city_name_en")),
                province=_optional_text(city.get("province")),
                country=_optional_text(city.get("country")) or "KR",
            ),
        )
    return tuple(identities)


def _metadata_city_identities(records: Sequence[Any]) -> tuple[CityIdentity, ...]:
    by_city_id: dict[str, CityIdentity] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        metadata = record.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        identity = _city_identity(metadata)
        if identity is None:
            continue
        by_city_id.setdefault(identity.city_id, identity)
    return tuple(by_city_id.values())


def _city_identity(metadata: Mapping[str, Any]) -> CityIdentity | None:
    city_id = _optional_text(metadata.get("city_id"))
    ddb_pk = _optional_text(metadata.get("ddb_pk"))
    if city_id is None or ddb_pk is None:
        return None
    return CityIdentity(
        city_id=city_id,
        ddb_pk=ddb_pk,
        city_name_ko=_optional_text(metadata.get("city_name_ko")),
        city_name_en=_optional_text(metadata.get("city_name_en")),
        province=_optional_text(metadata.get("province")),
        country=_optional_text(metadata.get("country")) or "KR",
    )


def _identity_for_city_select(
    city_select_input: Mapping[str, Any],
    city_map: CityIdentityMap,
) -> CityIdentity | None:
    for key in (
        "city_key",
        "cityKey",
        "destination_city_key",
        "destinationCityKey",
        "ddb_pk",
        "ddbPk",
        "destination_id",
        "destinationId",
        "destination_label",
        "destinationLabel",
    ):
        identity = city_map.get(city_select_input.get(key))
        if identity is not None:
            return identity
    return None


def _has_identity_hint(city_select_input: Mapping[str, Any]) -> bool:
    return any(
        city_select_input.get(key) is not None
        for key in (
            "city_key",
            "cityKey",
            "destination_city_key",
            "destinationCityKey",
            "ddb_pk",
            "ddbPk",
            "destination_id",
            "destinationId",
            "destination_label",
            "destinationLabel",
        )
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _lookup_key(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "CityIdentity",
    "CityIdentityMap",
    "DEFAULT_CITY_IDENTITY_MAP_PATH",
    "DEFAULT_CITY_METADATA_PATH",
    "build_city_identity_map_from_metadata",
    "enrich_city_select_identity",
    "load_city_identity_map",
    "load_default_city_identity_map",
]
