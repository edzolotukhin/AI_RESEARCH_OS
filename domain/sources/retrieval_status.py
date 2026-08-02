from __future__ import annotations

from enum import Enum


class RetrievalStatus(str, Enum):
    """Lifecycle status for an acquired research source."""

    ACQUIRED = "acquired"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    TRUNCATED = "truncated"
