"""Composition Root for Lovv Agent V2.

This module initializes dependencies (infra) and passes them to the graph components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.infra.memory.checkpointer import build_checkpointer
from lovv_agent_v2.core.graph import compile_v2_graph


@dataclass(frozen=True, slots=True)
class LovvLangGraphV2Harness:
    """Compiled LangGraph V2 plus its runtime configuration."""

    graph: Any
    config: RuntimeConfig

    def invoke(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        graph_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the V2 graph and return the output."""

        config = dict(graph_config or {})
        return self.graph.invoke(payload, config=config)


def build_v2_harness(
    config: RuntimeConfig,
    checkpointer: Any | None = None,
) -> LovvLangGraphV2Harness:
    """Build and compile the V2 recommendation graph."""

    graph = compile_v2_graph(checkpointer=checkpointer)
    return LovvLangGraphV2Harness(graph=graph, config=config)


def build_live_harness(
    config: RuntimeConfig | None = None,
) -> LovvLangGraphV2Harness:
    """Build a live harness from injected or environment config with checkpointer."""

    resolved_config = RuntimeConfig.from_env() if config is None else config
    checkpointer = build_checkpointer(resolved_config.memory)
    return build_v2_harness(config=resolved_config, checkpointer=checkpointer)


__all__ = ["LovvLangGraphV2Harness", "build_v2_harness", "build_live_harness"]

