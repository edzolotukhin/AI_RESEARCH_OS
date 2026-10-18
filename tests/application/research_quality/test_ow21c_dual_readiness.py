from functools import lru_cache

import pytest

from application.evidence.semantic_assignment import ValidatedSemanticAssignment
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from domain.evidence.evidence import Evidence
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.research_subject import ResearchSubject
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus


@lru_cache(maxsize=1)
def _design() -> ResearchDesign:
    subject = ResearchSubject.proposed(
        canonical_label="Добробут домогосподарств",
        canonical_language="uk",
    ).approve()
    return ResearchDesign(
        id="ow21c",
        language="uk",
        research_questions=(ResearchQuestion("rq", "Як змінився добробут?"),),
        information_needs=(
            InformationNeed(
                "in-a", "rq", "Доходи і зарплата",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.MIXED,
                    required_aspects=("aspect_a1", "aspect_a2"),
                ),
            ),
            InformationNeed(
                "in-b", "rq", "Споживчі ціни",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.MIXED,
                    required_aspects=("aspect_b1",),
                ),
            ),
            InformationNeed(
                "in-c", "rq", "Зайнятість",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.MIXED,
                    required_aspects=("aspect_c1",),
                ),
            ),
        ),
        research_subject=subject,
    )


def _evidence(
    evidence_id: str,
    *,
    need_id: str = "in-a",
    aspects: tuple[str, ...] | None = ("aspect_a1",),
    deduplication_key: str | None = None,
    stale_subject: bool = False,
) -> Evidence:
    design = _design()
    subject = design.research_subject
    assert subject is not None
    metadata = {}
    if aspects is not None:
        metadata["semantic_assignment"] = ValidatedSemanticAssignment(
            subject_id=subject.subject_id,
            subject_fingerprint=(
                "stale-fingerprint" if stale_subject else subject.semantic_fingerprint
            ),
            binding_type="canonical_subject",
            supporting_relation_id=None,
            information_need_id=need_id,
            required_aspect_refs=aspects,
            geography_applicability=(),
            semantic_justification="Grounded assignment.",
            lexical_diagnostics={},
        ).to_metadata()
    return Evidence(
        id=evidence_id,
        project_id="project",
        source_id=f"source-{evidence_id}",
        source_content_checksum=f"checksum-{evidence_id}",
        workflow_run_id="run",
        research_design_id="ow21c",
        research_question_refs=("rq",),
        information_need_refs=(need_id,),
        statement=f"Statement {evidence_id}",
        source_excerpt=f"Excerpt {evidence_id}",
        created_at="2026-10-17T00:00:00Z",
        deduplication_key=deduplication_key or f"dedup-{evidence_id}",
        metadata=metadata,
    )


def _signals(*evidence: Evidence, need_id: str = "in-a"):
    return next(
        item
        for item in DeterministicSufficiencyEvaluator().evaluate(
            design=_design(), evidence=evidence,
        )
        if item.information_need_id == need_id
    )


def _semantic(
    status: SufficiencyStatus,
    *,
    missing: tuple[str, ...] = (),
    gaps: tuple[GapType, ...] = (),
) -> SemanticSufficiencyAssessment:
    return SemanticSufficiencyAssessment(
        status=status,
        missing_aspects=missing,
        gap_types=gaps,
        search_directives=missing if status not in {
            SufficiencyStatus.SUFFICIENT,
            SufficiencyStatus.BLOCKED,
        } else (),
        confidence=0.8,
        reason="Bounded semantic assessment.",
    )


def _need_assessment(
    *,
    need_id: str,
    status: SufficiencyStatus,
    supported: tuple[str, ...] = (),
    current: bool = True,
    contradictions: tuple[str, ...] = (),
    gaps: tuple[GapType, ...] = (),
    evidence_count: int = 1,
) -> InformationNeedAssessment:
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id="rq",
        status=status,
        evidence_count=evidence_count,
        independent_source_count=min(1, evidence_count),
        supported_aspects=supported,
        contradictions=contradictions,
        gap_types=gaps,
        assessment_current=current,
        required_aspect_ids=(f"aspect_{need_id[-1]}1",),
    )


def _result(*assessments: InformationNeedAssessment):
    return build_research_readiness_result((
        build_research_readiness_assessment(
            research_question_id="rq",
            need_assessments=assessments,
        ),
    ))


def test_v2_single_aspect_ref_contributes_explicit_coverage():
    signals = _signals(_evidence("e1"))
    assessment = build_information_need_assessment(
        signals=signals,
        semantic=_semantic(SufficiencyStatus.PARTIAL, missing=("aspect_a2",)),
        information_need=_design().information_needs[0],
    )
    assert assessment.supported_aspects == ("aspect_a1",)


def test_v2_multiple_aspects_are_each_counted_once():
    signals = _signals(_evidence("e1", aspects=("aspect_a2", "aspect_a1")))
    assert signals.declared_supported_aspects == ("aspect_a1", "aspect_a2")


def test_v2_zero_aspect_evidence_contributes_zero_coverage():
    signals = _signals(_evidence("e1", aspects=()))
    assert signals.evidence_count == 1
    assert signals.declared_supported_aspects == ()


def test_duplicate_evidence_does_not_inflate_aspect_coverage():
    signals = _signals(
        _evidence("e1", deduplication_key="same"),
        _evidence("e2", deduplication_key="same"),
    )
    assert signals.evidence_count == 1
    assert signals.duplicate_evidence_count == 1
    assert signals.declared_supported_aspects == ("aspect_a1",)


def test_legacy_evidence_preserves_existing_coverage_derivation():
    signals = _signals(_evidence("legacy", aspects=None))
    assessment = build_information_need_assessment(
        signals=signals,
        semantic=_semantic(SufficiencyStatus.PARTIAL, missing=("aspect_a2",)),
        information_need=_design().information_needs[0],
    )
    assert assessment.supported_aspects == ("aspect_a1",)


def test_mixed_legacy_and_v2_uses_deterministic_v2_primary_coverage():
    evidence = (_evidence("legacy", aspects=None), _evidence("v2", aspects=("aspect_a2",)))
    first = _signals(*evidence)
    second = _signals(*reversed(evidence))
    assert first.declared_supported_aspects == second.declared_supported_aspects
    assessment = build_information_need_assessment(
        signals=first,
        semantic=_semantic(SufficiencyStatus.PARTIAL, missing=("aspect_a2",)),
        information_need=_design().information_needs[0],
    )
    assert assessment.supported_aspects == ("aspect_a2",)


def test_one_sufficient_need_makes_partial_analysis_ready_not_design_ready():
    result = _result(
        _need_assessment(need_id="in-a", status=SufficiencyStatus.SUFFICIENT),
        _need_assessment(
            need_id="in-b", status=SufficiencyStatus.MISSING, evidence_count=0,
            gaps=(GapType.NO_EVIDENCE,),
        ),
    )
    assert result.complete_design_ready is False
    assert result.ready_for_analysis is False
    assert result.analysis_ready is True
    assert result.analysis_eligible_information_need_ids == ("in-a",)


def test_partial_need_with_supported_aspect_is_analysis_eligible():
    result = _result(
        _need_assessment(
            need_id="in-a", status=SufficiencyStatus.PARTIAL,
            supported=("aspect_a1",), gaps=(GapType.INSUFFICIENT_DEPTH,),
        ),
        _need_assessment(
            need_id="in-b", status=SufficiencyStatus.MISSING, evidence_count=0,
            gaps=(GapType.NO_EVIDENCE,),
        ),
    )
    assert result.complete_design_ready is False
    assert result.analysis_ready is True
    assert result.analysis_eligible_information_need_ids == ("in-a",)


def test_insufficient_need_is_not_analysis_eligible():
    result = _result(_need_assessment(
        need_id="in-a", status=SufficiencyStatus.INSUFFICIENT,
        supported=("aspect_a1",), gaps=(GapType.INSUFFICIENT_DIVERSITY,),
    ))
    assert result.analysis_ready is False
    assert result.analysis_eligible_information_need_ids == ()


@pytest.mark.parametrize(
    "assessment",
    (
        _need_assessment(
            need_id="in-a", status=SufficiencyStatus.BLOCKED,
            supported=("aspect_a1",), gaps=(GapType.UNRESOLVABLE,),
        ),
        _need_assessment(
            need_id="in-a", status=SufficiencyStatus.PARTIAL,
            supported=("aspect_a1",), current=False, gaps=(GapType.STALE_EVIDENCE,),
        ),
        _need_assessment(
            need_id="in-a", status=SufficiencyStatus.PARTIAL,
            supported=("aspect_a1",), contradictions=("conflict",),
            gaps=(GapType.CONFLICTING_EVIDENCE,),
        ),
    ),
)
def test_blocked_stale_or_contradictory_need_is_not_eligible(assessment):
    assert _result(assessment).analysis_ready is False


def test_all_needs_sufficient_makes_both_readiness_decisions_true():
    result = _result(
        _need_assessment(need_id="in-b", status=SufficiencyStatus.SUFFICIENT),
        _need_assessment(need_id="in-a", status=SufficiencyStatus.SUFFICIENT),
    )
    assert result.complete_design_ready is True
    assert result.ready_for_analysis is True
    assert result.analysis_ready is True


def test_ready_for_analysis_remains_strict_complete_readiness_compatibility_field():
    result = _result(
        _need_assessment(need_id="in-a", status=SufficiencyStatus.SUFFICIENT),
        _need_assessment(
            need_id="in-b", status=SufficiencyStatus.MISSING, evidence_count=0,
            gaps=(GapType.NO_EVIDENCE,),
        ),
    )
    restored = type(result).from_dict(result.to_dict())
    assert restored.ready_for_analysis == restored.complete_design_ready
    assert restored.ready_for_analysis is False
    assert restored.analysis_ready is True
    assert ResearchReadinessGate().research_outcome(restored).value == (
        "insufficient_research"
    )


def test_analysis_eligible_ids_are_deterministically_ordered():
    result = _result(
        _need_assessment(need_id="in-b", status=SufficiencyStatus.SUFFICIENT),
        _need_assessment(need_id="in-a", status=SufficiencyStatus.SUFFICIENT),
    )
    assert result.analysis_eligible_information_need_ids == ("in-a", "in-b")


def test_v2_aspect_ref_does_not_bypass_source_diversity_sufficiency():
    signals = _signals(_evidence("e1"))
    assessment = build_information_need_assessment(
        signals=signals,
        semantic=_semantic(
            SufficiencyStatus.INSUFFICIENT,
            gaps=(GapType.INSUFFICIENT_DIVERSITY,),
        ),
        information_need=_design().information_needs[0],
    )
    result = _result(assessment)
    assert assessment.supported_aspects == ("aspect_a1",)
    assert result.analysis_ready is False


def test_stale_v2_assignment_contributes_no_coverage():
    signals = _signals(_evidence("e1", stale_subject=True))
    assert signals.evidence_count == 1
    assert signals.v2_semantic_assignment_count == 0
    assert signals.declared_supported_aspects == ()
