from __future__ import annotations

from enum import Enum


class RetrievalArm(str, Enum):
    """Provider-neutral semantic retrieval strategy."""

    BASELINE = "baseline"
    LOCALIZED = "localized"
