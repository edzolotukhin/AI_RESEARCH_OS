from __future__ import annotations

from enum import Enum


class ResearchOutcome(str, Enum):
    """Run-scoped research outcome distinct from technical workflow failure."""

    READY_FOR_ANALYSIS = "ready_for_analysis"
    INSUFFICIENT_RESEARCH = "insufficient_research"
