"""PROPERTY AI: terminal InformationNeed state truthfulness."""

from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.budget_aware_readiness import (
    apply_sufficiency_budget_termination,
)
from application.execution.exceptions import BudgetExhaustedError
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.research_loop_state import ResearchLoopState
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
    get_sufficiency_assessment_cache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)
from application.research_quality.terminal_state_reconciliation import (
    reconcile_terminal_readiness,
)
from tests.application.research_quality.test_targeted_research_loop import (
    _build_service,
    _context,
    _missing_result,
)


def _design(*need_ids: str) -> ResearchDesign:
    rq = ResearchQuestion(id="rq-1", question="What is supported?", objective_refs=())
    return ResearchDesign(
        id="design-1",
        research_questions=(rq,),
        information_needs=tuple(
            InformationNeed(
                id=need_id,
                research_question_id=rq.id,
                description=f"Need {need_id}",
            )
            for need_id in need_ids
        ),
    )


def _evidence(evidence_id: str, need_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id="project-1",
        source_id=f"source-{evidence_id}",
        source_content_checksum=f"checksum-{evidence_id}",
        workflow_run_id="run-1",
        research_design_id="design-1",
        statement=f"Statement {evidence_id}",
        source_excerpt=f"Excerpt {evidence_id}",
        created_at="2026-08-15T00:00:00Z",
        research_question_refs=("rq-1",),
        information_need_refs=(need_id,),
        deduplication_key=evidence_id,
    )


def _assessment(
    need_id: str,
    status: SufficiencyStatus,
    evidence_count: int,
) -> InformationNeedAssessment:
    gaps = () if status == SufficiencyStatus.SUFFICIENT else (GapType.INSUFFICIENT_DEPTH,)
    if status == SufficiencyStatus.MISSING:
        gaps = (GapType.NO_EVIDENCE,)
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id="rq-1",
        status=status,
        evidence_count=evidence_count,
        independent_source_count=evidence_count,
        gap_types=gaps,
        reason=f"Completed semantic assessment for {need_id}",
    )


def _result(*assessments: InformationNeedAssessment):
    rq = build_research_readiness_assessment(
        research_question_id="rq-1",
        need_assessments=assessments,
    )
    return build_research_readiness_result((rq,))


def _store(
    cache: SufficiencyAssessmentCache,
    design: ResearchDesign,
    need_id: str,
    evidence: tuple[Evidence, ...],
    assessment: InformationNeedAssessment,
) -> str:
    need = next(item for item in design.information_needs if item.id == need_id)
    fingerprint = build_sufficiency_assessment_fingerprint(
        information_need=need,
        research_question=design.research_questions[0],
        evidence_ids=tuple(item.id for item in evidence if need_id in item.information_need_refs),
        evidence_by_id={item.id: item for item in evidence},
        max_evidence_items=10,
    )
    cache.store(
        information_need_id=need_id,
        fingerprint=fingerprint,
        assessment=assessment,
    )
    return fingerprint


class TerminalInformationNeedTruthfulnessTests(unittest.TestCase):
    def test_loop_budget_stop_returns_partial_pass_cache_not_previous_snapshot(self) -> None:
        class PartialPassThenBudgetStop:
            def __init__(self) -> None:
                self.calls = 0

            def evaluate(self, *, design, evidence):
                self.calls += 1
                if self.calls == 1:
                    return _missing_result()
                cache = get_sufficiency_assessment_cache()
                self.assertIsNotNone(cache)
                need = design.information_needs[0]
                fingerprint = build_sufficiency_assessment_fingerprint(
                    information_need=need,
                    research_question=design.research_questions[0],
                    evidence_ids=tuple(item.id for item in evidence),
                    evidence_by_id={item.id: item for item in evidence},
                    max_evidence_items=10,
                )
                cache.store(
                    information_need_id=need.id,
                    fingerprint=fingerprint,
                    assessment=_assessment(
                        need.id,
                        SufficiencyStatus.INSUFFICIENT,
                        len(evidence),
                    ),
                )
                raise BudgetExhaustedError(
                    "downstream_reserve_exhausted",
                    stage="sufficiency",
                )

            def assertIsNotNone(self, value) -> None:
                if value is None:
                    raise AssertionError("sufficiency cache was not bound")

        evaluator = PartialPassThenBudgetStop()
        context = _context()
        result = _build_service(evaluator).assess_and_apply(context)
        need = result.research_question_assessments[0].information_need_assessments[0]
        loop_payload = context.read_shared("research_loop_state")

        self.assertEqual(evaluator.calls, 2)
        self.assertEqual(need.status, SufficiencyStatus.INSUFFICIENT)
        self.assertTrue(need.assessment_current)
        self.assertGreater(need.evidence_count, 0)
        self.assertEqual(result.termination_reason, "downstream_reserve_exhausted")
        self.assertEqual(loop_payload["pending_targeted_need_id"], "")
        self.assertEqual(loop_payload["pending_attempt"], 0)
        self.assertEqual(loop_payload["research_loop_count"], 1)
        self.assertTrue(
            loop_payload["history"][-1]["remediation_attempt_diagnostics"][
                "terminal_state_reconciled"
            ]
        )

    def test_matching_completed_cache_is_terminal_authority(self) -> None:
        design = _design("in-1")
        evidence = (_evidence("ev-1", "in-1"), _evidence("ev-2", "in-1"))
        previous = _result(_assessment("in-1", SufficiencyStatus.MISSING, 0))
        cache = SufficiencyAssessmentCache()
        fingerprint = _store(
            cache,
            design,
            "in-1",
            evidence,
            _assessment("in-1", SufficiencyStatus.INSUFFICIENT, 2),
        )

        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=evidence,
            previous=previous,
            cache_payload=cache.to_dict(),
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(need.evidence_count, 2)
        self.assertTrue(need.assessment_current)
        self.assertEqual(need.assessment_evidence_fingerprint, fingerprint)
        self.assertEqual(need.terminal_evidence_fingerprint, fingerprint)

    def test_zero_evidence_is_current_missing(self) -> None:
        design = _design("in-1")
        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=(),
            previous=_result(_assessment("in-1", SufficiencyStatus.MISSING, 0)),
            cache_payload=None,
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.MISSING)
        self.assertEqual(need.evidence_count, 0)
        self.assertEqual(need.terminal_evidence_count, 0)
        self.assertTrue(need.assessment_current)

    def test_changed_evidence_preserves_verdict_but_marks_it_stale(self) -> None:
        design = _design("in-12")
        assessed_evidence = tuple(_evidence(f"ev-{index}", "in-12") for index in range(36))
        terminal_evidence = assessed_evidence + tuple(
            _evidence(f"new-{index}", "in-12") for index in range(5)
        )
        prior = _assessment("in-12", SufficiencyStatus.PARTIAL, 36)
        cache = SufficiencyAssessmentCache()
        assessed_fingerprint = _store(cache, design, "in-12", assessed_evidence, prior)

        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=terminal_evidence,
            previous=_result(prior),
            cache_payload=cache.to_dict(),
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.PARTIAL)
        self.assertEqual(need.evidence_count, 36)
        self.assertEqual(need.terminal_evidence_count, 41)
        self.assertFalse(need.assessment_current)
        self.assertIn(GapType.STALE_EVIDENCE, need.gap_types)
        self.assertEqual(need.assessment_evidence_fingerprint, assessed_fingerprint)
        self.assertNotEqual(
            need.assessment_evidence_fingerprint,
            need.terminal_evidence_fingerprint,
        )
        self.assertFalse(terminal.ready_for_analysis)

    def test_stale_sufficient_assessment_cannot_make_run_ready(self) -> None:
        design = _design("in-1")
        assessed = (_evidence("ev-1", "in-1"),)
        terminal_evidence = (*assessed, _evidence("ev-2", "in-1"))
        prior = _assessment("in-1", SufficiencyStatus.SUFFICIENT, 1)
        cache = SufficiencyAssessmentCache()
        _store(cache, design, "in-1", assessed, prior)
        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=terminal_evidence,
            previous=_result(prior),
            cache_payload=cache.to_dict(),
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.SUFFICIENT)
        self.assertFalse(need.assessment_current)
        self.assertFalse(terminal.ready_for_analysis)
        self.assertTrue(terminal.targeted_research_required)

    def test_same_count_different_evidence_is_stale(self) -> None:
        design = _design("in-1")
        old = (_evidence("old", "in-1"),)
        current = (_evidence("new", "in-1"),)
        prior = _assessment("in-1", SufficiencyStatus.PARTIAL, 1)
        cache = SufficiencyAssessmentCache()
        _store(cache, design, "in-1", old, prior)
        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=current,
            previous=_result(prior),
            cache_payload=cache.to_dict(),
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertFalse(need.assessment_current)
        self.assertEqual(need.evidence_count, need.terminal_evidence_count)

    def test_mixed_partial_pass_uses_each_need_latest_completed_state(self) -> None:
        design = _design("in-1", "in-3", "in-12")
        previous = _result(
            _assessment("in-1", SufficiencyStatus.INSUFFICIENT, 6),
            _assessment("in-3", SufficiencyStatus.MISSING, 0),
            _assessment("in-12", SufficiencyStatus.PARTIAL, 36),
        )
        evidence = tuple(_evidence(f"in1-{i}", "in-1") for i in range(9)) + tuple(
            _evidence(f"in3-{i}", "in-3") for i in range(2)
        ) + tuple(_evidence(f"in12-{i}", "in-12") for i in range(41))
        cache = SufficiencyAssessmentCache()
        _store(cache, design, "in-1", evidence, _assessment("in-1", SufficiencyStatus.INSUFFICIENT, 9))
        _store(cache, design, "in-3", evidence, _assessment("in-3", SufficiencyStatus.INSUFFICIENT, 2))
        old_in12 = tuple(item for item in evidence if "in-12" in item.information_need_refs)[:36]
        _store(cache, design, "in-12", old_in12, _assessment("in-12", SufficiencyStatus.PARTIAL, 36))

        terminal = reconcile_terminal_readiness(
            design=design,
            evidence=evidence,
            previous=previous,
            cache_payload=cache.to_dict(),
        )
        needs = {
            item.information_need_id: item
            for item in terminal.research_question_assessments[0].information_need_assessments
        }
        self.assertEqual((needs["in-1"].evidence_count, needs["in-1"].assessment_current), (9, True))
        self.assertEqual((needs["in-3"].status, needs["in-3"].evidence_count), (SufficiencyStatus.INSUFFICIENT, 2))
        self.assertEqual((needs["in-12"].evidence_count, needs["in-12"].terminal_evidence_count), (36, 41))
        self.assertFalse(needs["in-12"].assessment_current)

    def test_budget_termination_keeps_reconciled_stale_metadata(self) -> None:
        design = _design("in-1")
        old = (_evidence("old", "in-1"),)
        current = (*old, _evidence("new", "in-1"))
        prior = _assessment("in-1", SufficiencyStatus.PARTIAL, 1)
        cache = SufficiencyAssessmentCache()
        _store(cache, design, "in-1", old, prior)
        reconciled = reconcile_terminal_readiness(
            design=design,
            evidence=current,
            previous=_result(prior),
            cache_payload=cache.to_dict(),
        )
        terminal, state = apply_sufficiency_budget_termination(
            reconciled,
            loop_state=ResearchLoopState(),
            reason="downstream_reserve_exhausted",
        )
        need = terminal.research_question_assessments[0].information_need_assessments[0]
        self.assertFalse(need.assessment_current)
        self.assertFalse(terminal.targeted_research_required)
        self.assertEqual(state.termination_reason, "downstream_reserve_exhausted")

    def test_reconciliation_is_deterministic_and_serializable(self) -> None:
        design = _design("in-b", "in-a")
        previous = _result(
            _assessment("in-b", SufficiencyStatus.MISSING, 0),
            _assessment("in-a", SufficiencyStatus.MISSING, 0),
        )
        first = reconcile_terminal_readiness(
            design=design,
            evidence=(),
            previous=previous,
            cache_payload=None,
        )
        second = reconcile_terminal_readiness(
            design=design,
            evidence=(),
            previous=previous,
            cache_payload=None,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(
            [item.information_need_id for item in first.research_question_assessments[0].information_need_assessments],
            ["in-a", "in-b"],
        )


if __name__ == "__main__":
    unittest.main()
