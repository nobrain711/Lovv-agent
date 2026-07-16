from __future__ import annotations

from typing import Any


def patch_langchain_callback_resume_compat() -> None:
    try:
        from langchain_core.callbacks.base import BaseCallbackHandler
    except ImportError:
        return
    if not hasattr(BaseCallbackHandler, "on_resume"):
        setattr(BaseCallbackHandler, "on_resume", _noop_on_resume)
    if not hasattr(BaseCallbackHandler, "on_interrupt"):
        setattr(BaseCallbackHandler, "on_interrupt", _noop_on_interrupt)


def _noop_on_resume(self: object, value: Any = None, **kwargs: Any) -> None:
    return None


def _noop_on_interrupt(self: object, value: Any = None, **kwargs: Any) -> None:
    return None


__all__ = ["patch_langchain_callback_resume_compat"]
