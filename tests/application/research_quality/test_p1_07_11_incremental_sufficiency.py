"""P1-07.11 incremental sufficiency fingerprint and reuse."""

from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
    _current_cache,
    clear_sufficiency_assessment_cache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)
from tests.application.research_quality.test_hybrid_sufficiency_evaluator import (
    RecordingSemanticAssessor,
    _design,
    _evidence,
    _semantic,
)


def _bind_cache(cache: SufficiencyAssessmentCache | None = None) -> SufficiencyAssessmentCache:
    resolved = cache or SufficiencyAssessmentCache()
    _current_cache.set(resolved)
    return resolved


class SufficiencyFingerprintTests(unittest.TestCase):
    def test_reordered_evidence_ids_same_fingerprint(self) -> None:
        design = _design(need_ids=("in-1",))
        need = design.information_needs[0]
        rq = design.research_questions[0]
        ev1 = _evidence(evidence_id="b-id", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="a-id", information_need_refs=("in-1",))
        by_id = {ev1.id: ev1, ev2.id: ev2}
        left = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev1.id, ev2.id),
            evidence_by_id=by_id,
            max_evidence_items=10,
        )
        right = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev2.id, ev1.id),
            evidence_by_id=by_id,
            max_evidence_items=10,
        )
        self.assertEqual(left, right)

    def test_added_or_removed_or_changed_evidence_changes_fingerprint(self) -> None:
        design = _design(need_ids=("in-1",))
        need = design.information_needs[0]
        rq = design.research_questions[0]
        ev1 = _evidence(evidence_id="ev-1")
        ev2 = _evidence(evidence_id="ev-2")
        base = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev1.id,),
            evidence_by_id={ev1.id: ev1},
            max_evidence_items=10,
        )
        added = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev1.id, ev2.id),
            evidence_by_id={ev1.id: ev1, ev2.id: ev2},
            max_evidence_items=10,
        )
        changed = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        changed.statement = "Different statement"
        changed_fp = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(changed.id,),
            evidence_by_id={changed.id: changed},
            max_evidence_items=10,
        )
        self.assertNotEqual(base, added)
        self.assertNotEqual(base, changed_fp)

    def test_need_definition_or_expectation_changes_fingerprint(self) -> None:
        rq = ResearchQuestion(id="rq-1", question="Q?", objective_refs=())
        need_a = InformationNeed(
            id="in-1",
            research_question_id="rq-1",
            description="Need A",
        )
        need_b = InformationNeed(
            id="in-1",
            research_question_id="rq-1",
            description="Need B",
        )
        ev = _evidence(evidence_id="ev-1")
        fp_a = build_sufficiency_assessment_fingerprint(
            information_need=need_a,
            research_question=rq,
            evidence_ids=(ev.id,),
            evidence_by_id={ev.id: ev},
            max_evidence_items=10,
        )
        fp_b = build_sufficiency_assessment_fingerprint(
            information_need=need_b,
            research_question=rq,
            evidence_ids=(ev.id,),
            evidence_by_id={ev.id: ev},
            max_evidence_items=10,
        )
        need_exp = InformationNeed(
            id="in-1",
            research_question_id="rq-1",
            description="Need A",
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE,
                required_aspects=("market_size",),
            ),
        )
        fp_exp = build_sufficiency_assessment_fingerprint(
            information_need=need_exp,
            research_question=rq,
            evidence_ids=(ev.id,),
            evidence_by_id={ev.id: ev},
            max_evidence_items=10,
        )
        self.assertNotEqual(fp_a, fp_b)
        self.assertNotEqual(fp_a, fp_exp)


class IncrementalSufficiencyEvaluatorTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()

    def test_identical_set_reuses_and_consumes_zero_llm(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),)
        design = _design(need_ids=("in-1",))
        first = evaluator.evaluate(design=design, evidence=evidence)
        second = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(cache.reused_assessments, 1)
        self.assertEqual(
            first.research_question_assessments[0].information_need_assessments[0].status,
            second.research_question_assessments[0].information_need_assessments[0].status,
        )

    def test_reordered_evidence_reuses(self) -> None:
        _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design(need_ids=("in-1",))
        ev_a = _evidence(evidence_id="ev-a", information_need_refs=("in-1",))
        ev_b = _evidence(evidence_id="ev-b", information_need_refs=("in-1",))
        evaluator.evaluate(design=design, evidence=(ev_a, ev_b))
        evaluator.evaluate(design=design, evidence=(ev_b, ev_a))
        self.assertEqual(len(semantic.calls), 1)

    def test_added_evidence_reassesses_once(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design(need_ids=("in-1",))
        ev1 = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="ev-2", information_need_refs=("in-1",))
        evaluator.evaluate(design=design, evidence=(ev1,))
        evaluator.evaluate(design=design, evidence=(ev1, ev2))
        self.assertEqual(len(semantic.calls), 2)
        self.assertEqual(cache.reassessed_fingerprint_changed, 1)

    def test_removed_evidence_reassesses(self) -> None:
        _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design(need_ids=("in-1",))
        ev1 = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="ev-2", information_need_refs=("in-1",))
        evaluator.evaluate(design=design, evidence=(ev1, ev2))
        evaluator.evaluate(design=design, evidence=(ev1,))
        self.assertEqual(len(semantic.calls), 2)

    def test_changed_need_definition_reassesses(self) -> None:
        _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        ev = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        evaluator.evaluate(design=_design(need_ids=("in-1",)), evidence=(ev,))
        changed = ResearchDesign(
            id="design-1",
            research_questions=_design().research_questions,
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Changed need text",
                ),
            ),
        )
        evaluator.evaluate(design=changed, evidence=(ev,))
        self.assertEqual(len(semantic.calls), 2)

    def test_changed_expectation_reassesses(self) -> None:
        _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        ev = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        evaluator.evaluate(design=_design(need_ids=("in-1",)), evidence=(ev,))
        with_exp = ResearchDesign(
            id="design-1",
            research_questions=_design().research_questions,
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need in-1",
                    evidence_expectation=EvidenceExpectation(
                        nature=EvidenceNature.QUALITATIVE,
                        required_aspects=("chef_usage",),
                    ),
                ),
            ),
        )
        evaluator.evaluate(design=with_exp, evidence=(ev,))
        self.assertEqual(len(semantic.calls), 2)

    def test_missing_prior_state_assesses(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="ev-1"),),
        )
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(cache.missing_prior_state, 1)

    def test_zero_evidence_remains_no_llm(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evaluator.evaluate(design=_design(need_ids=("in-1", "in-2")), evidence=())
        evaluator.evaluate(design=_design(need_ids=("in-1", "in-2")), evidence=())
        self.assertEqual(len(semantic.calls), 0)
        self.assertEqual(cache.missing_no_evidence, 4)

    def test_multi_in_selective_reassessment(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design(need_ids=("in-1", "in-2", "in-3"))
        ev1 = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="ev-2", information_need_refs=("in-2",))
        ev3 = _evidence(evidence_id="ev-3", information_need_refs=("in-3",))
        ev2b = _evidence(evidence_id="ev-2b", information_need_refs=("in-2",))
        evaluator.evaluate(design=design, evidence=(ev1, ev2, ev3))
        self.assertEqual(len(semantic.calls), 3)
        cache.reset_pass_diagnostics()
        evaluator.evaluate(design=design, evidence=(ev1, ev2, ev2b, ev3))
        self.assertEqual(len(semantic.calls), 4)
        self.assertEqual(cache.reused_need_ids, ["in-1", "in-3"])
        self.assertEqual(cache.reassessed_need_ids, ["in-2"])
