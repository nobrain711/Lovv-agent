from __future__ import annotations

import pytest
from langchain_core.callbacks.base import BaseCallbackHandler

from lovv_agent_v2.common.telemetry_callback_compat import (
    patch_langchain_callback_resume_compat,
)


def test_patch_langchain_callback_resume_compat_adds_noop_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if hasattr(BaseCallbackHandler, "on_resume"):
        monkeypatch.delattr(BaseCallbackHandler, "on_resume")

    patch_langchain_callback_resume_compat()

    handler = BaseCallbackHandler()
    assert handler.on_resume({"value": "ok"}, run_id="run-1") is None
