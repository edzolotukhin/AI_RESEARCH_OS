from __future__ import annotations

from enum import Enum


class ReviewVerdict(str, Enum):
    """Authoritative quality-gate decision for a report review attempt."""

    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"
