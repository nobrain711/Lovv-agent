from __future__ import annotations

import logging


def configure_runtime_logging() -> None:
    logging.getLogger("botocore.credentials").setLevel(logging.WARNING)


__all__ = ["configure_runtime_logging"]
