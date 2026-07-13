from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from lovv_agent_v2.tools.agentcore_credentials import resolve_agentcore_api_key
from lovv_agent_v2.tools.ors_results import durations_minutes, snapped_payloads
from lovv_agent_v2.tools.travel_time_provider import (
    HaversineTravelTimeProvider,
    MatrixResponse,
    SnapResponse,
)

class OrsProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OrsProviderConfig:
    module_file: Path
    timeout_sec: int = 20
    cache_dir: Path | None = None
    snap_radius_m: float = 300.0
    allow_fallback: bool = True
    load_env_local: bool = False


@dataclass(slots=True)
class OrsTravelTimeProvider:
    config: OrsProviderConfig
    api_key_resolver: Callable[[], str | None] | None = None
    _module: ModuleType | None = None
    _snapped_places: dict[str, object] | None = None
    _snap_payloads: dict[str, Mapping[str, object]] | None = None

    @classmethod
    def from_default(cls) -> OrsTravelTimeProvider:
        return cls(OrsProviderConfig(module_file=default_ors_module_file()))

    def snap_places(
        self,
        places: Sequence[Mapping[str, object]],
        transport_pref: str,
    ) -> SnapResponse:
        candidates, payload_by_id, missing_ids = self._candidates(places)
        fallback = HaversineTravelTimeProvider()
        if not candidates or not self._has_api_key():
            snap = fallback.snap_places(places, transport_pref)
            self._snap_payloads = {place_id: payload for place_id, payload in payload_by_id.items()}
            self._snapped_places = {place_id: candidate for place_id, candidate in candidates.items()}
            return _snap_with_audit(snap, "ors_external_haversine_presnap", missing_ids)
        module = self._ors_module()
        client = self._client(module)
        try:
            result = client.snap_places(
                list(candidates.values()),
                profile=_profile(transport_pref),
                radius_m=self.config.snap_radius_m,
            )
        except (ImportError, OSError, RuntimeError, ValueError):
            snap = fallback.snap_places(places, transport_pref)
            self._snap_payloads = {place_id: payload for place_id, payload in payload_by_id.items()}
            self._snapped_places = {place_id: candidate for place_id, candidate in candidates.items()}
            return _snap_with_audit(snap, "ors_external_snap_failure_fallback", missing_ids)
        snapped = snapped_payloads(payload_by_id, result)
        self._snap_payloads = snapped
        self._snapped_places = {
            place_id: place
            for place_id, place in zip(candidates, result.snapped_places, strict=True)
        }
        return SnapResponse(
            places=tuple(snapped.values()),
            excluded_place_ids=tuple(missing_ids),
            audit={
                "snap_provider": "ors_external",
                "snap_profile": result.profile,
                "snap_fallback_used": bool(result.fallback_used),
                "snap_radius_m": self.config.snap_radius_m,
                "snapped_place_ids": tuple(snapped),
                "unroutable_place_ids": tuple(missing_ids),
            },
        )

    def matrix_minutes(
        self,
        place_ids: tuple[str, ...],
        transport_pref: str,
    ) -> MatrixResponse:
        snapped_places = self._snapped_places or {}
        matrix_places = [snapped_places[place_id] for place_id in place_ids if place_id in snapped_places]
        if not matrix_places:
            return MatrixResponse(durations={}, audit={"matrix_provider": "ors_external_empty"})
        module = self._ors_module()
        client = self._client(module)
        result = client.get_matrix(
            matrix_places,
            profile=_profile(transport_pref),
            use_cache=True,
            allow_fallback=self.config.allow_fallback,
        )
        return MatrixResponse(
            durations=durations_minutes(result),
            audit={
                "matrix_provider": "ors_external",
                "duration_profile": result.profile,
                "duration_unit": "minutes",
                "fallback_used": result.source if result.fallback_used else "",
                "ors_source": result.source,
            },
        )

    def _ors_module(self) -> ModuleType:
        if self._module is None:
            self._module = _load_ors_module(self.config.module_file)
            if self.config.load_env_local and hasattr(self._module, "load_env_local"):
                self._module.load_env_local(str(self.config.module_file.parent / ".env.local"))
        return self._module

    def _client(self, module: ModuleType):
        return module.OrsMatrixClient(
            timeout_sec=self.config.timeout_sec,
            cache_dir=self.config.cache_dir,
        )

    def _candidates(
        self,
        places: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], dict[str, Mapping[str, object]], list[str]]:
        module = self._ors_module()
        candidates: dict[str, object] = {}
        payloads: dict[str, Mapping[str, object]] = {}
        missing_ids: list[str] = []
        for place in places:
            place_id = _place_id(place)
            coordinate = _coordinate_pair(place)
            if coordinate is None:
                missing_ids.append(place_id)
                continue
            lat, lon = coordinate
            candidates[place_id] = module.PlaceCandidate(
                place_id=place_id,
                title=_title(place),
                lat=lat,
                lon=lon,
                theme_tags=_theme_tags(place),
                subtype=_optional_text(place.get("subtype")),
                source_tier=_optional_text(place.get("source_tier")),
            )
            payloads[place_id] = place
        return candidates, payloads, missing_ids

    def _has_api_key(self) -> bool:
        if self.config.load_env_local:
            self._ors_module()
        if os.getenv("ORS_API_KEY"):
            return True
        resolver = self.api_key_resolver or resolve_agentcore_api_key
        agentcore_key = resolver()
        if agentcore_key is None:
            return False
        os.environ["ORS_API_KEY"] = agentcore_key
        return True


def default_ors_module_file() -> Path:
    env_dir = os.getenv("LOVV_ORS_CODE_DIR")
    if env_dir:
        return Path(env_dir) / "ors_matrix.py"
    return Path(__file__).resolve().parent / "ors_helper" / "ors_matrix.py"


def ors_provider_from_env(
    api_key_resolver: Callable[[], str | None] = resolve_agentcore_api_key,
) -> OrsTravelTimeProvider | None:
    enabled = os.getenv("LOVV_PLANNER_TRAVEL_TIME_PROVIDER") == "ors" or os.getenv("LOVV_ENABLE_ORS") == "1"
    if not enabled:
        return None
    module_file = default_ors_module_file()
    if not module_file.exists():
        raise OrsProviderUnavailableError(f"ORS module file not found: {module_file}")
    return OrsTravelTimeProvider(
        OrsProviderConfig(
            module_file=module_file,
            cache_dir=_cache_dir(),
            load_env_local=os.getenv("LOVV_ORS_LOAD_ENV_LOCAL") == "1",
        ),
        api_key_resolver=api_key_resolver,
    )


def _load_ors_module(module_file: Path) -> ModuleType:
    if not module_file.exists():
        raise OrsProviderUnavailableError(f"ORS module file not found: {module_file}")
    spec = importlib.util.spec_from_file_location("_lovv_external_ors_matrix", module_file)
    if spec is None or spec.loader is None:
        raise OrsProviderUnavailableError(f"ORS module cannot be loaded: {module_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cache_dir() -> Path | None:
    value = os.getenv("LOVV_ORS_CACHE_DIR")
    return Path(value) if value else Path(".ors_cache")


def _profile(transport_pref: str) -> str:
    return "foot-walking" if transport_pref == "walk" else "driving-car"


def _snap_with_audit(
    snap: SnapResponse,
    provider: str,
    missing_ids: Sequence[str],
) -> SnapResponse:
    return SnapResponse(
        places=snap.places,
        excluded_place_ids=tuple((*snap.excluded_place_ids, *missing_ids)),
        audit={**dict(snap.audit), "snap_provider": provider, "unroutable_place_ids": tuple(missing_ids)},
    )

def _place_id(place: Mapping[str, object]) -> str:
    value = place.get("place_id", place.get("placeId"))
    if not isinstance(value, str) or not value.strip():
        raise OrsProviderUnavailableError("ORS place payload requires place_id")
    return value.strip()


def _title(place: Mapping[str, object]) -> str:
    value = place.get("title")
    return value.strip() if isinstance(value, str) and value.strip() else _place_id(place)


def _coordinate_pair(place: Mapping[str, object]) -> tuple[float, float] | None:
    lat = _coordinate(place, "latitude", "lat")
    lon = _coordinate(place, "longitude", "lon")
    if lat is None or lon is None:
        return None
    return lat, lon


def _coordinate(place: Mapping[str, object], key: str, alt_key: str) -> float | None:
    value = place.get(key, place.get(alt_key))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _theme_tags(place: Mapping[str, object]) -> list[str] | None:
    value = place.get("theme_tags", place.get("themeTags"))
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        return None
    return [item for item in value if isinstance(item, str)]


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
