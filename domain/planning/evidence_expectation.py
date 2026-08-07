from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.common.exceptions import ValidationError
from domain.planning.aspect_identifiers import canonical_aspect_ids
from domain.planning.evidence_nature import EvidenceNature


def _optional_normalized_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_minimum_independent_sources(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValidationError(
            "minimum_independent_sources must be >= 1 when present, "
            f"got {value}",
        )
    return value


@dataclass(frozen=True)
class EvidenceExpectation:
    """
    Target requirement contract defining what counts as an answer for one
    InformationNeed. This is not an assessment, search plan, or readiness
    decision.
    """

    nature: EvidenceNature
    required_aspects: tuple[str, ...] = ()
    geography: str | None = None
    timeframe: str | None = None
    minimum_independent_sources: int | None = None
    requires_quantitative_evidence: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.nature, EvidenceNature):
            object.__setattr__(
                self,
                "nature",
                EvidenceNature(str(self.nature)),
            )
        object.__setattr__(
            self,
            "required_aspects",
            canonical_aspect_ids(self.required_aspects),
        )
        object.__setattr__(
            self,
            "geography",
            _optional_normalized_text(self.geography),
        )
        object.__setattr__(
            self,
            "timeframe",
            _optional_normalized_text(self.timeframe),
        )
        object.__setattr__(
            self,
            "minimum_independent_sources",
            _validate_minimum_independent_sources(self.minimum_independent_sources),
        )
        if not isinstance(self.requires_quantitative_evidence, bool):
            raise ValidationError(
                "requires_quantitative_evidence must be a bool",
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "nature": self.nature.value,
            "required_aspects": list(self.required_aspects),
            "requires_quantitative_evidence": self.requires_quantitative_evidence,
        }
        if self.geography is not None:
            payload["geography"] = self.geography
        if self.timeframe is not None:
            payload["timeframe"] = self.timeframe
        if self.minimum_independent_sources is not None:
            payload["minimum_independent_sources"] = self.minimum_independent_sources
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceExpectation:
        minimum_sources = payload.get("minimum_independent_sources")
        return cls(
            nature=EvidenceNature(str(payload["nature"])),
            required_aspects=canonical_aspect_ids(
                payload.get("required_aspects"),
            ),
            geography=payload.get("geography"),
            timeframe=payload.get("timeframe"),
            minimum_independent_sources=(
                int(minimum_sources)
                if minimum_sources is not None
                else None
            ),
            requires_quantitative_evidence=bool(
                payload.get("requires_quantitative_evidence", False),
            ),
        )
