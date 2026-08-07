from __future__ import annotations

from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchDesign
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import (
    ACTIONABLE_BLOCKING_STATUSES,
    READINESS_BLOCKING_STATUSES,
    SufficiencyStatus,
)

from application.research_quality.exceptions import SemanticSufficiencyAssessmentError


def build_information_need_assessment(
    *,
    signals: DeterministicSufficiencySignals,
    semantic: SemanticSufficiencyAssessment | None,
) -> InformationNeedAssessment:
    """Merge deterministic facts with optional semantic judgment."""
    if signals.evidence_count == 0:
        return InformationNeedAssessment(
            information_need_id=signals.information_need_id,
            research_question_id=signals.research_question_id,
            status=SufficiencyStatus.MISSING,
            evidence_count=0,
            independent_source_count=0,
            gap_types=(GapType.NO_EVIDENCE,),
            reason=_missing_reason(signals),
        )

    if semantic is None:
        raise ValueError(
            "semantic assessment is required when evidence_count > 0",
        )

    status = semantic.status
    if status == SufficiencyStatus.MISSING and signals.evidence_count > 0:
        status = SufficiencyStatus.INSUFFICIENT

    gap_types = _merge_gap_types(
        signals.deterministic_gap_types,
        semantic.gap_types,
    )
    _assert_consistent_need_assessment(
        status=status,
        evidence_count=signals.evidence_count,
        gap_types=gap_types,
        missing_aspects=semantic.missing_aspects,
        search_directives=semantic.search_directives,
    )
    return InformationNeedAssessment(
        information_need_id=signals.information_need_id,
        research_question_id=signals.research_question_id,
        status=status,
        evidence_count=signals.evidence_count,
        independent_source_count=signals.independent_source_count,
        source_quality=(
            signals.source_quality_score if signals.source_quality_available else None
        ),
        freshness=signals.freshness_score if signals.freshness_available else None,
        source_diversity=(
            signals.source_diversity_score if signals.source_diversity_available else None
        ),
        quantitative_evidence_present=signals.quantitative_evidence_present,
        contradictions=signals.contradictions,
        missing_aspects=semantic.missing_aspects,
        gap_types=gap_types,
        search_directives=semantic.search_directives,
        confidence=semantic.confidence,
        reason=semantic.reason,
    )


def build_research_readiness_assessment(
    *,
    research_question_id: str,
    need_assessments: Sequence[InformationNeedAssessment],
) -> ResearchReadinessAssessment:
    sorted_assessments = tuple(
        sorted(need_assessments, key=lambda item: item.information_need_id),
    )
    ready = all(
        assessment.status == SufficiencyStatus.SUFFICIENT
        for assessment in sorted_assessments
    )
    blocking_ids = tuple(
        assessment.information_need_id
        for assessment in sorted_assessments
        if assessment.status in READINESS_BLOCKING_STATUSES
    )
    if ready:
        reason = "All information needs sufficient."
    else:
        blocking_statuses = [
            assessment.status.value
            for assessment in sorted_assessments
            if assessment.status in READINESS_BLOCKING_STATUSES
        ]
        reason = "Blocking information needs: " + ", ".join(blocking_statuses)
    return ResearchReadinessAssessment(
        research_question_id=research_question_id,
        information_need_assessments=sorted_assessments,
        ready_for_analysis=ready,
        blocking_information_need_ids=blocking_ids if not ready else (),
        reason=reason,
    )


def build_research_readiness_result(
    rq_assessments: Sequence[ResearchReadinessAssessment],
) -> ResearchReadinessResult:
    sorted_assessments = tuple(
        sorted(rq_assessments, key=lambda item: item.research_question_id),
    )
    all_ready = all(
        assessment.ready_for_analysis for assessment in sorted_assessments
    )
    blocking_rq_ids = tuple(
        assessment.research_question_id
        for assessment in sorted_assessments
        if not assessment.ready_for_analysis
    )
    blocking_need_ids = tuple(
        need.information_need_id
        for assessment in sorted_assessments
        for need in assessment.information_need_assessments
        if need.status in READINESS_BLOCKING_STATUSES
    )
    has_actionable = any(
        need.status in ACTIONABLE_BLOCKING_STATUSES
        for assessment in sorted_assessments
        for need in assessment.information_need_assessments
    )
    if all_ready:
        targeted = False
    else:
        targeted = has_actionable

    return ResearchReadinessResult(
        research_question_assessments=sorted_assessments,
        ready_for_analysis=all_ready,
        blocking_research_question_ids=blocking_rq_ids if not all_ready else (),
        blocking_information_need_ids=blocking_need_ids if not all_ready else (),
        targeted_research_required=targeted,
    )


def _missing_reason(signals: DeterministicSufficiencySignals) -> str:
    if signals.warnings:
        return "No relevant evidence mapped to this information need. " + "; ".join(
            signals.warnings,
        )
    return "No relevant evidence mapped to this information need."


def _merge_gap_types(
    deterministic: tuple[GapType, ...],
    semantic: tuple[GapType, ...],
) -> tuple[GapType, ...]:
    merged: list[GapType] = []
    seen: set[GapType] = set()
    for gap_type in (*deterministic, *semantic):
        if gap_type == GapType.NO_EVIDENCE:
            continue
        if gap_type not in seen:
            seen.add(gap_type)
            merged.append(gap_type)
    return tuple(sorted(merged, key=lambda item: item.value))


def _assert_consistent_need_assessment(
    *,
    status: SufficiencyStatus,
    evidence_count: int,
    gap_types: tuple[GapType, ...],
    missing_aspects: tuple[str, ...],
    search_directives: tuple[str, ...],
) -> None:
    """Fail fast before constructing an invalid InformationNeedAssessment."""
    if status != SufficiencyStatus.SUFFICIENT:
        return

    blocking = [
        gap_type.value
        for gap_type in gap_types
        if gap_type in BLOCKING_GAP_TYPES
    ]
    if evidence_count == 0 or blocking or missing_aspects or search_directives:
        raise SemanticSufficiencyAssessmentError(
            "Inconsistent semantic sufficiency assessment: SUFFICIENT status requires "
            "evidence_count > 0 and no blocking gap_types, missing_aspects, or "
            "search_directives.",
        )
