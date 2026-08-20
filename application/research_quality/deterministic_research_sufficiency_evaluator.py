from __future__ import annotations

from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.evidence_payload import DEFAULT_MAX_EVIDENCE_ITEMS
from application.research_quality.sufficiency_assessment_cache import (
    get_sufficiency_assessment_cache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)


class DeterministicResearchSufficiencyEvaluator:
    """Always-ready sufficiency evaluator for smoke/deterministic workflows."""

    def __init__(
        self,
        *,
        deterministic_evaluator: DeterministicSufficiencyEvaluator | None = None,
    ) -> None:
        self._deterministic = (
            deterministic_evaluator or DeterministicSufficiencyEvaluator()
        )

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence,
    ) -> ResearchReadinessResult:
        signals_list = self._deterministic.evaluate(design=design, evidence=evidence)
        rq_assessments = []
        needs_by_rq: dict[str, list] = {}
        needs_by_id = {need.id: need for need in design.information_needs}
        rq_by_id = {rq.id: rq for rq in design.research_questions}
        evidence_by_id = {item.id: item for item in evidence}
        cache = get_sufficiency_assessment_cache()
        for signals in signals_list:
            need = needs_by_id.get(signals.information_need_id)
            assessment = build_information_need_assessment(
                signals=signals,
                semantic=(
                    None
                    if signals.evidence_count == 0
                    else SemanticSufficiencyAssessment(
                        status=SufficiencyStatus.SUFFICIENT,
                        reason="Deterministic readiness pass.",
                    )
                ),
                information_need=need,
            )
            if cache is not None and need is not None:
                if signals.evidence_count == 0:
                    cache.record_missing(need.id)
                else:
                    cache.store(
                        information_need_id=need.id,
                        fingerprint=build_sufficiency_assessment_fingerprint(
                            information_need=need,
                            research_question=rq_by_id[need.research_question_id],
                            evidence_ids=signals.evidence_ids,
                            evidence_by_id=evidence_by_id,
                            max_evidence_items=DEFAULT_MAX_EVIDENCE_ITEMS,
                        ),
                        assessment=assessment,
                    )
            needs_by_rq.setdefault(signals.research_question_id, []).append(assessment)

        for rq in sorted(design.research_questions, key=lambda item: item.id):
            rq_assessments.append(
                build_research_readiness_assessment(
                    research_question_id=rq.id,
                    need_assessments=needs_by_rq.get(rq.id, ()),
                ),
            )
        return build_research_readiness_result(rq_assessments)
