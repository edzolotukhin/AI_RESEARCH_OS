from __future__ import annotations

from enum import Enum


class FindingType(str, Enum):
    """Analytical conclusion category derived from grounded Evidence."""

    SYNTHESIS = "synthesis"
    COMPARISON = "comparison"
    TREND = "trend"
    CONTRADICTION = "contradiction"
