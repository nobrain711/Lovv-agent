"""AgentCoreMemorySaver checkpointer builder."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from lovv_agent_v2.common.telemetry_memory import (
    emit_memory_guard,
    memory_guard_log_entry,
)
from lovv_agent_v2.infra.config import MemorySettings


def build_checkpointer(memory: MemorySettings) -> Any:
    """Build the configured checkpointer.

    Memory-disabled local runs still need multi-turn state, so they use LangGraph's
    process-local MemorySaver. AgentCore Memory is used only when explicitly enabled.
    """

    if not memory.enabled:
        _emit_checkpointer_guard("local_memory_saver", "agentcore_memory_disabled", False)
        return MemorySaver()

    try:
        # Dynamic import to avoid module loading errors in local dev environments
        aws_checkpoint_module = import_module("langgraph_checkpoint_aws")
        AgentCoreMemorySaver = getattr(aws_checkpoint_module, "AgentCoreMemorySaver")

        if not memory.memory_id:
            raise RuntimeError("LOVV_MEMORY_ID is required when LOVV_MEMORY_ENABLED=True")
        _emit_checkpointer_guard("agentcore_memory_saver", "agentcore_memory_enabled", True)
        return AgentCoreMemorySaver(memory.memory_id)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "langgraph-checkpoint-aws package is required when LOVV_MEMORY_ENABLED=True. "
            "Please ensure it is installed in the target runtime environment."
        ) from exc


def _emit_checkpointer_guard(
    memory_mode: str,
    event_guard: str,
    memory_id_configured: bool,
) -> None:
    emit_memory_guard(
        memory_guard_log_entry(
            memory_mode=memory_mode,
            event_guard=event_guard,
            memory_id_configured=memory_id_configured,
        ),
    )


__all__ = ["build_checkpointer"]

