from __future__ import annotations

from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.research_readiness_result import ResearchReadinessResult

from application.ports.research_quality_ports import SemanticSufficiencyAssessor
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.evidence_payload import (
    DEFAULT_MAX_EVIDENCE_ITEMS,
    select_bounded_evidence,
)
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)


class HybridResearchSufficiencyEvaluator:
    """Hybrid deterministic + semantic research sufficiency evaluator (P1-03)."""

    def __init__(
        self,
        *,
        deterministic_evaluator: DeterministicSufficiencyEvaluator | None = None,
        semantic_assessor: SemanticSufficiencyAssessor,
        max_evidence_items: int = DEFAULT_MAX_EVIDENCE_ITEMS,
    ) -> None:
        self._deterministic = (
            deterministic_evaluator or DeterministicSufficiencyEvaluator()
        )
        self._semantic = semantic_assessor
        self._max_evidence_items = max_evidence_items

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        signals_by_need = {
            signals.information_need_id: signals
            for signals in self._deterministic.evaluate(
                design=design,
                evidence=evidence,
            )
        }
        evidence_by_id = {item.id: item for item in evidence}

        need_assessments_by_rq: dict[str, list] = {
            rq.id: [] for rq in design.research_questions
        }
        sorted_needs = sorted(
            design.information_needs,
            key=lambda need: (need.research_question_id, need.id),
        )
        for need in sorted_needs:
            signals = signals_by_need[need.id]
            assessment = self._assess_need(
                design=design,
                need=need,
                signals=signals,
                evidence_by_id=evidence_by_id,
            )
            need_assessments_by_rq[need.research_question_id].append(assessment)

        rq_assessments = [
            build_research_readiness_assessment(
                research_question_id=rq.id,
                need_assessments=need_assessments_by_rq.get(rq.id, ()),
            )
            for rq in sorted(
                design.research_questions,
                key=lambda item: item.id,
            )
        ]
        return build_research_readiness_result(rq_assessments)

    def _assess_need(
        self,
        *,
        design: ResearchDesign,
        need: InformationNeed,
        signals: DeterministicSufficiencySignals,
        evidence_by_id: dict[str, Evidence],
    ):
        if signals.evidence_count == 0:
            return build_information_need_assessment(signals=signals, semantic=None)

        mapped_evidence = tuple(
            evidence_by_id[item_id]
            for item_id in signals.evidence_ids
            if item_id in evidence_by_id
        )
        bounded = select_bounded_evidence(
            mapped_evidence,
            max_items=self._max_evidence_items,
        )
        research_question = _research_question_for_need(design, need)
        semantic = self._semantic.assess(
            research_question=research_question,
            information_need=need,
            evidence=bounded,
            deterministic_signals=signals,
        )
        return build_information_need_assessment(signals=signals, semantic=semantic)


def _research_question_for_need(
    design: ResearchDesign,
    need: InformationNeed,
) -> ResearchQuestion:
    for rq in design.research_questions:
        if rq.id == need.research_question_id:
            return rq
    raise ValueError(
        f"InformationNeed {need.id!r} references unknown research_question_id "
        f"{need.research_question_id!r}",
    )
