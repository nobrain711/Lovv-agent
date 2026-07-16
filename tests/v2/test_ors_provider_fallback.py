from __future__ import annotations

import os
from pathlib import Path

from pytest import MonkeyPatch

import lovv_agent_v2.tools.agentcore_credentials as agentcore_credentials
import lovv_agent_v2.tools.ors_provider as ors_provider
from lovv_agent_v2.tools.ors_helper import ors_matrix
from lovv_agent_v2.common.telemetry_metrics import (
    aggregate_tool_metrics,
    reset_tool_calls,
    restore_tool_calls,
    tool_calls_since,
)
from lovv_agent_v2.tools.ors_provider import (
    OrsProviderConfig,
    OrsTravelTimeProvider,
)


def _place(place_id: str, title: str) -> dict[str, object]:
    return {
        "place_id": place_id,
        "title": title,
        "theme_tags": ["바다·해안"],
        "latitude": 38.2 if place_id == "raw-1" else 38.3,
        "longitude": 128.6,
    }


def test_ors_provider_snap_failure_falls_back_to_haversine(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module_file = tmp_path / "ors_matrix.py"
    module_file.write_text(
        "\n".join(
            (
                "class PlaceCandidate:",
                "    def __init__(self, place_id, title, lat, lon, theme_tags=None, subtype=None, source_tier=None):",
                "        self.place_id = place_id",
                "        self.title = title",
                "        self.lat = lat",
                "        self.lon = lon",
                "",
                "class MatrixResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.place_ids = [place.place_id for place in places]",
                "        self.durations_sec = [[0.0 if a == b else 180.0 for b in self.place_ids] for a in self.place_ids]",
                "        self.fallback_used = True",
                "        self.source = 'ors_haversine'",
                "",
                "class OrsMatrixClient:",
                "    def __init__(self, timeout_sec=20, cache_dir=None):",
                "        self.timeout_sec = timeout_sec",
                "        self.cache_dir = cache_dir",
                "",
                "    def snap_places(self, places, profile, radius_m=300):",
                "        raise RuntimeError('snap timeout')",
                "",
                "    def get_matrix(self, places, profile, use_cache=True, allow_fallback=True):",
                "        raise AssertionError('matrix must not run after snap failure')",
                "",
            ),
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORS_API_KEY", "fake")
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=module_file, cache_dir=None, load_env_local=False),
    )

    snapped = provider.snap_places((_place("raw-1", "해변"), _place("raw-2", "등대")), "car")
    matrix = provider.matrix_minutes(("raw-1", "raw-2"), "car")

    assert snapped.audit["snap_provider"] == "ors_external_snap_failure_fallback"
    assert [place["place_id"] for place in snapped.places] == ["raw-1", "raw-2"]
    assert matrix.audit["matrix_provider"] == "ors_external"
    assert matrix.audit["ors_source"] == "ors_haversine"
    assert matrix.durations[("raw-1", "raw-2")] > 0.0


def test_ors_helper_snap_fallback_skips_external_matrix(monkeypatch: MonkeyPatch) -> None:
    def timeout_request(*args: object, **kwargs: object) -> object:
        raise TimeoutError("snap timeout")

    def fail_matrix(*args: object, **kwargs: object) -> object:
        raise AssertionError("matrix must not run after helper fallback")

    monkeypatch.setenv("ORS_API_KEY", "fake")
    monkeypatch.setattr(ors_matrix, "_post_json", timeout_request)
    monkeypatch.setattr(ors_matrix.OrsMatrixClient, "get_matrix", fail_matrix)
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=Path(ors_matrix.__file__)),
    )
    provider._module = ors_matrix

    snapped = provider.snap_places((_place("raw-1", "해변"), _place("raw-2", "등대")), "car")
    matrix = provider.matrix_minutes(("raw-1", "raw-2"), "car")

    assert snapped.audit["snap_fallback_used"] is True
    assert matrix.audit["ors_source"] == "ors_haversine"
    assert matrix.durations[("raw-1", "raw-2")] > 0.0


def test_ors_provider_records_external_latency_metrics(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module_file = tmp_path / "ors_matrix.py"
    module_file.write_text(
        "\n".join(
            (
                "class PlaceCandidate:",
                "    def __init__(self, place_id, title, lat, lon, theme_tags=None, subtype=None, source_tier=None):",
                "        self.place_id = place_id",
                "        self.title = title",
                "        self.lat = lat",
                "        self.lon = lon",
                "",
                "class MatrixResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.place_ids = [place.place_id for place in places]",
                "        self.durations_sec = [[0.0 if a == b else 180.0 for b in self.place_ids] for a in self.place_ids]",
                "        self.fallback_used = False",
                "        self.source = 'ors'",
                "",
                "class SnapResult:",
                "    def __init__(self, profile, places):",
                "        self.profile = profile",
                "        self.original_places = places",
                "        self.snapped_places = places",
                "        self.snapped_distances_m = [0.0 for _ in places]",
                "        self.road_names = ['' for _ in places]",
                "        self.fallback_used = False",
                "",
                "class OrsMatrixClient:",
                "    def __init__(self, timeout_sec=20, cache_dir=None):",
                "        self.timeout_sec = timeout_sec",
                "        self.cache_dir = cache_dir",
                "",
                "    def snap_places(self, places, profile, radius_m=300):",
                "        return SnapResult(profile, places)",
                "",
                "    def get_matrix(self, places, profile, use_cache=True, allow_fallback=True):",
                "        return MatrixResult(profile, places)",
                "",
            ),
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORS_API_KEY", "fake")
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=module_file, cache_dir=None, load_env_local=False),
    )
    token = reset_tool_calls()
    try:
        provider.snap_places((_place("raw-1", "해변"), _place("raw-2", "등대")), "car")
        provider.matrix_minutes(("raw-1", "raw-2"), "car")
        metrics = aggregate_tool_metrics(tool_calls_since(0))
    finally:
        restore_tool_calls(token)

    assert metrics is not None
    assert metrics["ors.SnapPlaces"]["count"] == 1
    assert metrics["ors.GetMatrix"]["count"] == 1


def test_default_ors_module_file_is_packaged_with_src() -> None:
    module_file = ors_provider.default_ors_module_file()

    assert "lovv_agent_v2" in module_file.parts
    assert module_file.name == "ors_matrix.py"
    assert module_file.exists()


def test_ors_api_base_uses_heigit_gateway() -> None:
    assert ors_matrix.ORS_API_BASE == "https://api.heigit.org/openrouteservice"


def test_ors_provider_from_env_uses_packaged_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LOVV_ENABLE_ORS", "1")
    monkeypatch.delenv("LOVV_PLANNER_TRAVEL_TIME_PROVIDER", raising=False)
    monkeypatch.delenv("LOVV_ORS_CODE_DIR", raising=False)

    provider = ors_provider.ors_provider_from_env(api_key_resolver=lambda: None)

    assert provider is not None
    assert provider.config.module_file == ors_provider.default_ors_module_file()


def test_ors_provider_uses_agentcore_credential_when_env_key_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "")
    monkeypatch.setattr(
        ors_provider,
        "resolve_agentcore_api_key",
        lambda: "resolved-ors-key",
    )
    provider = OrsTravelTimeProvider(
        OrsProviderConfig(module_file=tmp_path / "ors_matrix.py"),
    )

    assert provider._has_api_key()
    assert os.environ["ORS_API_KEY"] == "resolved-ors-key"


def test_agentcore_credential_provider_resolves_ors_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    class FakeAgentCoreClient:
        def get_workload_access_token_for_user_id(
            self,
            *,
            workloadName: str,
            userId: str,
        ) -> dict[str, str]:
            assert workloadName == "LovvAgentCore_LovvAgentV2"
            assert userId == "lovv-runtime"
            return {"workloadAccessToken": "token-1"}

        def get_resource_api_key(
            self,
            *,
            workloadIdentityToken: str,
            resourceCredentialProviderName: str,
        ) -> dict[str, str]:
            assert workloadIdentityToken == "token-1"
            assert resourceCredentialProviderName == "ors_service_key"
            return {"apiKey": "resolved-ors-key"}

    monkeypatch.delenv("ORS_API_KEY", raising=False)
    monkeypatch.setenv("CREDENTIAL_ORS_SERVICE_KEY_NAME", "ors_service_key")
    monkeypatch.setenv("LOVV_AGENTCORE_WORKLOAD_NAME", "LovvAgentCore_LovvAgentV2")
    monkeypatch.setenv("LOVV_AGENTCORE_USER_ID", "lovv-runtime")
    api_key = agentcore_credentials.resolve_agentcore_api_key(
        client=FakeAgentCoreClient(),
    )

    assert api_key == "resolved-ors-key"
