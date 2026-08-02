from __future__ import annotations

from enum import Enum


class EvidenceType(str, Enum):
    DIRECT_EXCERPT = "direct_excerpt"
    FACTUAL_CLAIM = "factual_claim"
