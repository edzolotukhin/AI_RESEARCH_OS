from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.planning.aspect_identifiers import canonical_aspect_ids
from domain.research_quality._helpers import validate_unit_score


def _normalize_reason(value: Any) -> str:
    return str(value).strip()


@dataclass(frozen=True)
class RawSemanticDecision:
    """Semantic facts produced by a future semantic assessor."""

    supported_aspects: tuple[str, ...] = ()
    missing_aspects: tuple[str, ...] = ()
    semantic_conflicts: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "supported_aspects",
            canonical_aspect_ids(
                self.supported_aspects,
                field_name="supported_aspects",
            ),
        )
        object.__setattr__(
            self,
            "missing_aspects",
            canonical_aspect_ids(
                self.missing_aspects,
                field_name="missing_aspects",
            ),
        )
        object.__setattr__(
            self,
            "semantic_conflicts",
            canonical_aspect_ids(
                self.semantic_conflicts,
                field_name="semantic_conflicts",
            ),
        )
        validate_unit_score("confidence", self.confidence)
        object.__setattr__(self, "reason", _normalize_reason(self.reason))

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported_aspects": list(self.supported_aspects),
            "missing_aspects": list(self.missing_aspects),
            "semantic_conflicts": list(self.semantic_conflicts),
            "confidence": self.confidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawSemanticDecision:
        return cls(
            supported_aspects=canonical_aspect_ids(
                payload.get("supported_aspects"),
                field_name="supported_aspects",
            ),
            missing_aspects=canonical_aspect_ids(
                payload.get("missing_aspects"),
                field_name="missing_aspects",
            ),
            semantic_conflicts=canonical_aspect_ids(
                payload.get("semantic_conflicts"),
                field_name="semantic_conflicts",
            ),
            confidence=float(payload.get("confidence", 0.0)),
            reason=payload.get("reason", ""),
        )
