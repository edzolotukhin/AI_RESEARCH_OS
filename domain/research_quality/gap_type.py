from __future__ import annotations

from enum import Enum


class GapType(str, Enum):
    """Generic vocabulary for information-need research gaps."""

    NO_EVIDENCE = "no_evidence"
    INSUFFICIENT_DEPTH = "insufficient_depth"
    INSUFFICIENT_DIVERSITY = "insufficient_diversity"
    MISSING_QUANTITATIVE_DATA = "missing_quantitative_data"
    STALE_EVIDENCE = "stale_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT_SOURCE_QUALITY = "insufficient_source_quality"
    UNRESOLVABLE = "unresolvable"


BLOCKING_GAP_TYPES = frozenset(
    {
        GapType.NO_EVIDENCE,
        GapType.INSUFFICIENT_DEPTH,
        GapType.INSUFFICIENT_DIVERSITY,
        GapType.MISSING_QUANTITATIVE_DATA,
        GapType.STALE_EVIDENCE,
        GapType.CONFLICTING_EVIDENCE,
        GapType.INSUFFICIENT_SOURCE_QUALITY,
    },
)
