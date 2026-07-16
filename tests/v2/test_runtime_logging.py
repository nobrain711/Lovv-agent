from __future__ import annotations

import logging

from lovv_agent_v2.common.runtime_logging import configure_runtime_logging


def test_configure_runtime_logging_suppresses_botocore_credentials_info() -> None:
    logger = logging.getLogger("botocore.credentials")
    original_level = logger.level
    try:
        logger.setLevel(logging.NOTSET)

        configure_runtime_logging()

        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(original_level)
