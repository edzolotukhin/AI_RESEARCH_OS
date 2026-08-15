"""Deterministic terminal reconciliation after a partial sufficiency pass."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult

from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.evidence_payload import DEFAULT_MAX_EVIDENCE_ITEMS
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)


def reconcile_terminal_readiness(
    *,
    design: ResearchDesign,
    evidence: Sequence[Evidence],
    previous: ResearchReadinessResult,
    cache_payload: dict | None,
    max_evidence_items: int = DEFAULT_MAX_EVIDENCE_ITEMS,
) -> ResearchReadinessResult:
    """Build a truthful terminal snapshot without semantic or external calls.

    A completed cached assessment is authoritative only when its deterministic
    input fingerprint matches terminal Evidence. Zero-Evidence needs remain
    deterministically MISSING. Every other unmatched need preserves its last
    completed semantic assessment but is explicitly marked non-current.
    """
    signals_by_need = {
        item.information_need_id: item
        for item in DeterministicSufficiencyEvaluator().evaluate(
            design=design,
            evidence=evidence,
        )
    }
    evidence_by_id = {item.id: item for item in evidence}
    cache = SufficiencyAssessmentCache.from_dict(cache_payload)
    previous_by_need = {
        item.information_need_id: item
        for rq in previous.research_question_assessments
        for item in rq.information_need_assessments
    }
    rq_by_id = {item.id: item for item in design.research_questions}
    assessments_by_rq: dict[str, list[InformationNeedAssessment]] = {
        item.id: [] for item in design.research_questions
    }

    for need in sorted(
        design.information_needs,
        key=lambda item: (item.research_question_id, item.id),
    ):
        signals = signals_by_need[need.id]
        research_question = _research_question_for_need(need, rq_by_id)
        terminal_fingerprint = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=research_question,
            evidence_ids=signals.evidence_ids,
            evidence_by_id=evidence_by_id,
            max_evidence_items=max_evidence_items,
        )
        completed = cache.completed_entry(need.id)

        if signals.evidence_count == 0:
            assessment = build_information_need_assessment(
                signals=signals,
                semantic=None,
                information_need=need,
            )
            assessment = replace(
                assessment,
                assessment_current=True,
                assessment_evidence_fingerprint=terminal_fingerprint,
                terminal_evidence_fingerprint=terminal_fingerprint,
                terminal_evidence_count=0,
            )
        elif completed is not None and completed[0] == terminal_fingerprint:
            assessment = replace(
                completed[1],
                assessment_current=True,
                assessment_evidence_fingerprint=terminal_fingerprint,
                terminal_evidence_fingerprint=terminal_fingerprint,
                terminal_evidence_count=signals.evidence_count,
            )
        else:
            prior_fingerprint = completed[0] if completed is not None else ""
            prior = completed[1] if completed is not None else previous_by_need.get(need.id)
            if prior is None:
                raise ValueError(
                    "terminal reconciliation requires a prior completed assessment "
                    f"for positive-Evidence InformationNeed {need.id!r}",
                )
            gap_types = tuple(
                sorted({*prior.gap_types, GapType.STALE_EVIDENCE}, key=lambda item: item.value)
            )
            assessment = replace(
                prior,
                gap_types=gap_types,
                reason=(
                    "Terminal Evidence changed after the last completed semantic "
                    "assessment; the preserved status is non-current. " + prior.reason
                ),
                assessment_current=False,
                assessment_evidence_fingerprint=(
                    prior_fingerprint or prior.assessment_evidence_fingerprint
                ),
                terminal_evidence_fingerprint=terminal_fingerprint,
                terminal_evidence_count=signals.evidence_count,
            )
        assessments_by_rq[need.research_question_id].append(assessment)

    rq_assessments = tuple(
        build_research_readiness_assessment(
            research_question_id=rq.id,
            need_assessments=assessments_by_rq.get(rq.id, ()),
        )
        for rq in sorted(design.research_questions, key=lambda item: item.id)
    )
    return build_research_readiness_result(rq_assessments)


def _research_question_for_need(
    need: InformationNeed,
    rq_by_id: dict[str, ResearchQuestion],
) -> ResearchQuestion:
    research_question = rq_by_id.get(need.research_question_id)
    if research_question is None:
        raise ValueError(
            f"InformationNeed {need.id!r} references unknown research_question_id "
            f"{need.research_question_id!r}",
        )
    return research_question
