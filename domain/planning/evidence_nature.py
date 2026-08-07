from __future__ import annotations

from enum import Enum


class EvidenceNature(str, Enum):
    """Expected evidence nature for an InformationNeed."""

    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    MIXED = "mixed"
