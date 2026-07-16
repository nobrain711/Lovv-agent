from __future__ import annotations

from typing import Any

from lovv_agent_v2.common.telemetry_memory import MemoryEventInspector
from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.tools.agentcore_credentials import resolve_agentcore_api_key
from lovv_agent_v2.tools.ors_provider import (
    OrsProviderUnavailableError,
    ors_provider_from_env,
)
from lovv_agent_v2.tools.travel_time_provider import HaversineTravelTimeProvider


def build_live_travel_time_provider(client_provider: Any) -> Any:
    try:
        provider = ors_provider_from_env(
            api_key_resolver=lambda: resolve_agentcore_api_key(
                client=client_provider.create_agentcore_identity_client(),
            ),
        )
    except OrsProviderUnavailableError:
        provider = None
    return provider or HaversineTravelTimeProvider()


def memory_event_runtime(config: RuntimeConfig, client_provider: Any) -> dict[str, Any]:
    if not config.memory.enabled or not config.memory.memory_id:
        return {}
    return {
        "memory_event_inspector": MemoryEventInspector(
            client=client_provider.create_agentcore_identity_client(),
            memory_id=config.memory.memory_id,
        ),
    }


__all__ = ["build_live_travel_time_provider", "memory_event_runtime"]
