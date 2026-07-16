from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from typing import Callable, TypeVar

ResultT = TypeVar("ResultT")


def submit_with_context(
    executor: ThreadPoolExecutor,
    func: Callable[[], ResultT],
) -> Future[ResultT]:
    context = copy_context()
    return executor.submit(context.run, func)


__all__ = ["submit_with_context"]
