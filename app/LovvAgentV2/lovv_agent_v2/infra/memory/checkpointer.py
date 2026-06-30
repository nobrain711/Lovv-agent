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

        kwargs: dict[str, Any] = {}
        if memory.memory_id:
            kwargs["memory_id"] = memory.memory_id
        if memory.kms_key_arn:
            kwargs["kms_key_arn"] = memory.kms_key_arn
        
        # Mapping event_expiry_days to checkpointer lifespan configurations
        kwargs["event_expiry_days"] = memory.event_expiry_days

        return AgentCoreMemorySaver(**kwargs)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "langgraph-checkpoint-aws package is required when LOVV_MEMORY_ENABLED=True. "
            "Please ensure it is installed in the target runtime environment."
        ) from exc


__all__ = ["build_checkpointer"]

