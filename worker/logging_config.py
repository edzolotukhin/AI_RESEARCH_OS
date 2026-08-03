from __future__ import annotations

import logging
import sys


def configure_worker_logging() -> logging.Logger:
    """Configure bounded operational logging for the background worker process."""
    logger = logging.getLogger("ai_research_os.worker")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s %(message)s"),
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
