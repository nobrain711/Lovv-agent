from __future__ import annotations

import sys
from types import ModuleType

import pytest

from lovv_agent_v2.infra.config import MemorySettings
from lovv_agent_v2.infra.memory.checkpointer import build_checkpointer


class FakeAgentCoreMemorySaver:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def test_build_checkpointer_requires_agentcore_saver_package_when_memory_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "langgraph_checkpoint_aws", None)

    with pytest.raises(RuntimeError, match="langgraph-checkpoint-aws package is required"):
        build_checkpointer(MemorySettings(enabled=True))


def test_build_checkpointer_passes_only_memory_id_to_agentcore_saver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = ModuleType("langgraph_checkpoint_aws")
    FakeAgentCoreMemorySaver.calls.clear()
    setattr(fake_module, "AgentCoreMemorySaver", FakeAgentCoreMemorySaver)
    monkeypatch.setitem(sys.modules, "langgraph_checkpoint_aws", fake_module)

    saver = build_checkpointer(
        MemorySettings(
            enabled=True,
            memory_id="arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/test",
            event_expiry_days=30,
            kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/test",
        )
    )

    assert isinstance(saver, FakeAgentCoreMemorySaver)
    assert FakeAgentCoreMemorySaver.calls == [
        (("arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/test",), {})
    ]
