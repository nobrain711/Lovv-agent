"""AgentCoreMemorySaver checkpointer builder."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from lovv_agent_v2.infra.config import MemorySettings


def build_checkpointer(memory: MemorySettings) -> Any | None:
    """Build and return the AgentCoreMemorySaver checkpointer if enabled.

    Returns None if memory is disabled. Dynamically imports langgraph-checkpoint-aws
    to ensure import safety in local non-AWS environments.
    """

    if not memory.enabled:
        return None

    try:
        # Dynamic import to avoid module loading errors in local dev environments
        aws_checkpoint_module = import_module("langgraph_checkpoint_aws")
        AgentCoreMemorySaver = getattr(aws_checkpoint_module, "AgentCoreMemorySaver")

        if not memory.memory_id:
            raise RuntimeError("LOVV_MEMORY_ID is required when LOVV_MEMORY_ENABLED=True")
        return AgentCoreMemorySaver(memory.memory_id)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "langgraph-checkpoint-aws package is required when LOVV_MEMORY_ENABLED=True. "
            "Please ensure it is installed in the target runtime environment."
        ) from exc


__all__ = ["build_checkpointer"]

