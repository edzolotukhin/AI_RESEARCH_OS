from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any
from uuid import uuid4

from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.research_subject import ResearchSubject
from domain.planning.derivation import InformationNeedKind, DerivationContract, validate_dependency_graph


@dataclass(frozen=True)
class ResearchQuestion:
    """Semantic research question within a desk research design."""

    id: str
    question: str
    # Exact brief objective text; matched via normalize_objective_text().
    objective_refs: tuple[str, ...] = ()
    priority: int = 1
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "objective_refs": list(self.objective_refs),
            "priority": self.priority,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchQuestion:
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            objective_refs=_tuple_of_str(payload.get("objective_refs")),
            priority=int(payload.get("priority", 1)),
            rationale=str(payload.get("rationale", "")),
        )


class TemporalGranularity(StrEnum):
    UNSPECIFIED = "unspecified"
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    OTHER = "other"


@dataclass(frozen=True)
class EvidenceCoverageContract:
    """Explicit, immutable coverage requirements for one InformationNeed."""

    temporal_granularity: TemporalGranularity = TemporalGranularity.UNSPECIFIED
    required_periods: tuple[str, ...] = ()
    required_observations: tuple[str, ...] = ()
    required_metric: str = ""
    required_authority_kinds: tuple[str, ...] = ()
    # Each inner tuple is an OR-group; all groups must be satisfied.  The
    # legacy flat field remains one OR-group for backward compatibility.
    required_authority_kind_groups: tuple[tuple[str, ...], ...] = ()
    minimum_independent_sources: int = 1
    geography: str = ""
    eligible_source_types: tuple[str, ...] = ()
    prohibited_source_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "temporal_granularity",
            TemporalGranularity(self.temporal_granularity),
        )
        for field_name in (
            "required_periods",
            "required_observations",
            "required_authority_kinds",
            "eligible_source_types",
            "prohibited_source_patterns",
        ):
            object.__setattr__(self, field_name, _tuple_of_str(getattr(self, field_name)))
        object.__setattr__(self, "required_metric", self.required_metric.strip())
        object.__setattr__(self, "geography", self.geography.strip())
        if self.minimum_independent_sources < 1:
            raise ValueError("minimum_independent_sources must be >= 1")
        if (
            self.temporal_granularity == TemporalGranularity.QUARTERLY
            and any(not _is_quarter_period(item) for item in self.required_periods)
        ):
            raise ValueError("quarterly coverage requires explicit YYYY-QN periods")
        groups = tuple(_tuple_of_str(group) for group in self.required_authority_kind_groups)
        object.__setattr__(self, "required_authority_kind_groups", groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "temporal_granularity": self.temporal_granularity.value,
            "required_periods": list(self.required_periods),
            "required_observations": list(self.required_observations),
            "required_metric": self.required_metric,
            "required_authority_kinds": list(self.required_authority_kinds),
            "required_authority_kind_groups": [list(group) for group in self.required_authority_kind_groups],
            "minimum_independent_sources": self.minimum_independent_sources,
            "geography": self.geography,
            "eligible_source_types": list(self.eligible_source_types),
            "prohibited_source_patterns": list(self.prohibited_source_patterns),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceCoverageContract":
        return cls(
            temporal_granularity=TemporalGranularity(
                str(payload.get("temporal_granularity", "unspecified"))
            ),
            required_periods=_tuple_of_str(payload.get("required_periods")),
            required_observations=_tuple_of_str(payload.get("required_observations")),
            required_metric=str(payload.get("required_metric", "")),
            required_authority_kinds=_tuple_of_str(
                payload.get("required_authority_kinds")
            ),
            required_authority_kind_groups=tuple(
                _tuple_of_str(group)
                for group in payload.get("required_authority_kind_groups", ())
            ),
            minimum_independent_sources=int(
                payload.get("minimum_independent_sources", 1)
            ),
            geography=str(payload.get("geography", "")),
            eligible_source_types=_tuple_of_str(payload.get("eligible_source_types")),
            prohibited_source_patterns=_tuple_of_str(
                payload.get("prohibited_source_patterns")
            ),
        )


@dataclass(frozen=True)
class InformationNeed:
    """Information required to answer a research question (DR-03 prep)."""

    id: str
    research_question_id: str
    description: str
    priority: int = 1
    preferred_source_types: tuple[str, ...] = ()
    timeframe: str = ""
    geography: str = ""
    evidence_expectation: EvidenceExpectation | None = None
    evidence_coverage: EvidenceCoverageContract | None = None
    kind: InformationNeedKind = InformationNeedKind.ACQUIRED
    depends_on_information_need_ids: tuple[str, ...] = ()
    derivation: DerivationContract | None = None

    def __post_init__(self):
        object.__setattr__(self,"kind",InformationNeedKind(self.kind))
        object.__setattr__(self,"depends_on_information_need_ids",tuple(self.depends_on_information_need_ids))
        if len(set(self.depends_on_information_need_ids))!=len(self.depends_on_information_need_ids):
            raise ValueError("Duplicate dependency IDs")
        if self.kind==InformationNeedKind.DERIVED:
            if not isinstance(self.derivation,DerivationContract) or not self.depends_on_information_need_ids:
                raise ValueError("DERIVED requires dependencies and an executable derivation")
        elif self.derivation is not None:
            raise ValueError("Only DERIVED may carry a derivation")
        if self.kind==InformationNeedKind.ACQUIRED and self.depends_on_information_need_ids:
            raise ValueError("ACQUIRED cannot depend on analysis results")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "research_question_id": self.research_question_id,
            "description": self.description,
            "priority": self.priority,
            "preferred_source_types": list(self.preferred_source_types),
            "timeframe": self.timeframe,
            "geography": self.geography,
        }
        if self.evidence_expectation is not None:
            payload["evidence_expectation"] = self.evidence_expectation.to_dict()
        if self.evidence_coverage is not None:
            payload["evidence_coverage"] = self.evidence_coverage.to_dict()
        # Keep legacy snapshot serialization/fingerprints unchanged.
        if self.kind!=InformationNeedKind.ACQUIRED or self.depends_on_information_need_ids:
            payload["kind"]=self.kind.value
            payload["depends_on_information_need_ids"]=list(self.depends_on_information_need_ids)
        if self.derivation is not None:
            payload["derivation"]=self.derivation.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InformationNeed:
        raw_expectation = payload.get("evidence_expectation")
        evidence_expectation = (
            EvidenceExpectation.from_dict(raw_expectation)
            if isinstance(raw_expectation, dict)
            else None
        )
        raw_coverage = payload.get("evidence_coverage")
        evidence_coverage = (
            EvidenceCoverageContract.from_dict(raw_coverage)
            if isinstance(raw_coverage, dict)
            else None
        )
        return cls(
            id=str(payload["id"]),
            research_question_id=str(payload["research_question_id"]),
            description=str(payload["description"]),
            priority=int(payload.get("priority", 1)),
            preferred_source_types=_tuple_of_str(
                payload.get("preferred_source_types"),
            ),
            timeframe=str(payload.get("timeframe", "")),
            geography=str(payload.get("geography", "")),
            evidence_expectation=evidence_expectation,
            evidence_coverage=evidence_coverage,
            kind=InformationNeedKind(payload.get("kind","ACQUIRED")),
            depends_on_information_need_ids=tuple(payload.get("depends_on_information_need_ids",())),
            derivation=DerivationContract.from_dict(payload["derivation"]) if payload.get("derivation") is not None else None,
        )


@dataclass(frozen=True)
class ResearchDesign:
    """
    Semantic desk research design: how a brief will be investigated.

    Not the runtime workflow, search results, or deliverable artifacts.
    """

    id: str
    research_questions: tuple[ResearchQuestion, ...]
    information_needs: tuple[InformationNeed, ...] = ()
    source_strategy: tuple[str, ...] = ()
    analysis_plan: tuple[str, ...] = ()
    deliverable_plan: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    language: str = "en"
    research_subject: ResearchSubject | None = None

    def __post_init__(self):
        if any(n.kind!=InformationNeedKind.ACQUIRED or n.depends_on_information_need_ids for n in self.information_needs):
            validate_dependency_graph(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "research_questions": [
                question.to_dict() for question in self.research_questions
            ],
            "information_needs": [
                need.to_dict() for need in self.information_needs
            ],
            "source_strategy": list(self.source_strategy),
            "analysis_plan": list(self.analysis_plan),
            "deliverable_plan": list(self.deliverable_plan),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "language": self.language,
            "research_subject": (
                self.research_subject.to_dict() if self.research_subject is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ResearchDesign | None:
        if payload is None:
            return None
        return cls(
            id=str(payload.get("id") or uuid4()),
            research_questions=tuple(
                ResearchQuestion.from_dict(item)
                for item in payload.get("research_questions", [])
            ),
            information_needs=tuple(
                InformationNeed.from_dict(item)
                for item in payload.get("information_needs", [])
            ),
            source_strategy=_tuple_of_str(payload.get("source_strategy")),
            analysis_plan=_tuple_of_str(payload.get("analysis_plan")),
            deliverable_plan=_tuple_of_str(payload.get("deliverable_plan")),
            assumptions=_tuple_of_str(payload.get("assumptions")),
            limitations=_tuple_of_str(payload.get("limitations")),
            language=str(payload.get("language", "en") or "en"),
            research_subject=ResearchSubject.from_dict(payload.get("research_subject")),
        )


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, (list, tuple)):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return tuple(normalized)
    return ()


def _is_quarter_period(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"20\d{2}-Q[1-4]", value.strip(), re.IGNORECASE))


def research_design_field_names() -> tuple[str, ...]:
    return tuple(field.name for field in fields(ResearchDesign))
