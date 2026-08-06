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
        for signals in signals_list:
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
