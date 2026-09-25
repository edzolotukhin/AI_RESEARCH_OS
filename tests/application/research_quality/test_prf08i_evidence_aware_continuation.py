"""Offline PRF-08I coverage: source coverage is not Evidence coverage."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from application.config import ApplicationConfig
from application.evidence.temporal_scope import qualifying_evidence
from application.execution.budget_utils import (
    EVIDENCE_PURPOSE_INITIAL,
    EVIDENCE_PURPOSE_REMEDIATION,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from application.research_quality.evidence_gap_priority import (
    BELOW_SUFFICIENCY,
    NO_EVIDENCE,
    NO_QUALIFYING_EVIDENCE,
    evidence_priority_by_need,
)
from application.research_quality.gap_scheduler import decide_next_actionable_gap
from application.research_quality.gap_selection import select_actionable_gaps
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from tests.application.research_quality.test_prf08e_completeness import (
    _brief, _design, _evidence,
)
from tests.application.research_quality.test_targeted_research_loop import (
    StaticSufficiencyEvaluator,
    _build_service,
    _context,
    _design as _single_need_design,
    _design_two_needs,
    _design_three_needs,
    _need_assessment,
    _result_for_needs,
    _seed_evidence,
)


def _lowcost_budget():
    env = {
        "LLM_MAX_CALLS_PER_RUN": "24",
        "EVIDENCE_MAX_LLM_CALLS": "8",
        "SUFFICIENCY_MAX_LLM_CALLS": "6",
        "ANALYSIS_MAX_LLM_CALLS": "2",
        "REPORT_MAX_LLM_CALLS": "2",
        "REVIEW_MAX_CALLS": "1",
    }
    with patch.dict(os.environ, env):
        os.environ.pop("EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS", None)
        return create_execution_budget(ApplicationConfig.from_env())


def _request(need_id: str, rq_id: str) -> TargetedResearchRequest:
    return TargetedResearchRequest(
        workflow_run_id="offline-run", research_design_id="offline-design",
        research_question_id=rq_id, information_need_id=need_id,
        gap_types=(GapType.NO_EVIDENCE,),
    )


class _BudgetedEmptyRunner:
    def __init__(self) -> None:
        self.need_ids: list[str] = []

    def run(self, context, request):
        from application.execution.execution_budget_context import get_execution_budget

        budget = get_execution_budget()
        assert budget is not None
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.need_ids.append(request.information_need_id)
        return TargetedResearchIterationResult(
            source_ids=(), evidence_ids=(), queries_executed=1,
            sources_acquired=0, evidence_extracted=0,
            extraction_attempted=True,
        )


class EvidenceAwareContinuationTests(unittest.TestCase):
    def test_low_cost_profile_reallocates_not_increases_eight_calls(self) -> None:
        budget = _lowcost_budget()
        self.assertEqual((budget.evidence_initial_allowance,
                          budget.evidence_remediation_reserved), (6, 2))
        for _ in range(6):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)
        for _ in range(2):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(budget.stage_calls("evidence"), 8)

    def test_temporally_rejected_measurement_is_not_qualifying_coverage(self) -> None:
        design = _design()
        raw = (_evidence("later", "IN1", "There were 100 devices",
                         "There were 100 devices in August 2026.", "August 2026"),)
        eligible = qualifying_evidence(design=design, evidence=raw, brief=_brief())
        self.assertEqual(len(eligible), 0)
        ranks = evidence_priority_by_need(design=design, raw=raw, qualifying=eligible)
        self.assertEqual(ranks["IN1"], NO_QUALIFYING_EVIDENCE)
        self.assertEqual(ranks["IN2"], NO_EVIDENCE)

    def test_qualifying_evidence_below_sufficiency_is_distinct(self) -> None:
        design = _design()
        raw = (_evidence("definition", "IN2", "Connector means an outlet",
                         "A connector is defined as an outlet on a device."),)
        eligible = qualifying_evidence(design=design, evidence=raw, brief=_brief())
        self.assertEqual(len(eligible), 1)
        ranks = evidence_priority_by_need(design=design, raw=raw, qualifying=eligible)
        self.assertEqual(ranks["IN2"], BELOW_SUFFICIENCY)
        self.assertEqual(ranks["IN1"], NO_EVIDENCE)

    def test_scheduler_prioritizes_zero_then_nonqualifying_then_weak(self) -> None:
        gaps = (
            _request("IN1", "RQ1"), _request("IN2", "RQ2"),
            _request("IN3", "RQ3"),
        )
        priority = {"IN1": BELOW_SUFFICIENCY,
                    "IN2": NO_QUALIFYING_EVIDENCE, "IN3": NO_EVIDENCE}
        decision = decide_next_actionable_gap(
            gaps, gap_attempt_counts={}, stalled_need_ids=set(),
            max_attempts_per_gap=1, evidence_priority_by_need=priority,
        )
        self.assertEqual(decision.selected.information_need_id, "IN3")
        self.assertEqual(decision.evidence_priority_by_need["IN3"], NO_EVIDENCE)
        second = decide_next_actionable_gap(
            gaps, gap_attempt_counts={"IN3": 1}, stalled_need_ids=set(),
            max_attempts_per_gap=1, evidence_priority_by_need=priority,
        )
        self.assertEqual(second.selected.information_need_id, "IN2")

    def test_sufficient_need_is_not_actionable_while_zero_need_is(self) -> None:
        design = _design_two_needs()
        result = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1",
                             status=SufficiencyStatus.SUFFICIENT),
            _need_assessment(need_id="in-2", rq_id="rq-2",
                             status=SufficiencyStatus.MISSING),
        )
        gaps = select_actionable_gaps(
            result=result, design=design, workflow_run_id="offline-run",
            attempt=1, existing_source_ids=(), existing_evidence_ids=(),
        )
        self.assertEqual([gap.information_need_id for gap in gaps], ["in-2"])

    def test_failed_gap_stalls_and_bounded_alternative_gets_a_turn(self) -> None:
        gaps = (_request("IN1", "RQ1"), _request("IN2", "RQ2"))
        first = decide_next_actionable_gap(
            gaps, gap_attempt_counts={}, stalled_need_ids=set(),
            max_attempts_per_gap=1,
            evidence_priority_by_need={"IN1": NO_EVIDENCE, "IN2": NO_EVIDENCE},
        )
        self.assertEqual(first.selected.information_need_id, "IN1")
        second = decide_next_actionable_gap(
            gaps, gap_attempt_counts={"IN1": 1}, stalled_need_ids={"IN1"},
            max_attempts_per_gap=1,
            evidence_priority_by_need={"IN1": NO_EVIDENCE, "IN2": NO_EVIDENCE},
        )
        self.assertEqual(second.selected.information_need_id, "IN2")
        exhausted = decide_next_actionable_gap(
            gaps, gap_attempt_counts={"IN1": 1, "IN2": 1},
            stalled_need_ids={"IN1", "IN2"}, max_attempts_per_gap=1,
        )
        self.assertIsNone(exhausted.selected)

    def test_prf08h_pattern_source_complete_but_evidence_empty_continues_bounded(self) -> None:
        design = _design_three_needs()
        context = _context(design=design)
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        for need in design.information_needs:
            source_repo.create(Source(
                id=f"source-{need.id}", project_id=context.project.id,
                url=f"https://example.org/{need.id}",
                canonical_url=f"https://example.org/{need.id}",
                title=f"Synthetic {need.id}",
                retrieved_at="2026-01-01T00:00:00+00:00",
                retrieval_status=RetrievalStatus.ACQUIRED,
                content_text="Synthetic page with no extracted Evidence",
                workflow_run_refs=(context.workflow_run.id,),
                research_design_refs=(design.id,),
                information_need_refs=(need.id,),
                research_question_refs=(need.research_question_id,),
            ))
        context.write_shared("source_acquisition", {
            "coverage_complete_early_stop": True,
            "coverage_target_satisfied": True,
            "information_needs_covered_count": 3,
            "information_needs_total": 3,
        })
        missing = _result_for_needs(*(
            _need_assessment(need_id=need.id,
                             rq_id=need.research_question_id,
                             status=SufficiencyStatus.MISSING)
            for need in design.information_needs
        ))
        runner = _BudgetedEmptyRunner()
        service = _build_service(
            StaticSufficiencyEvaluator(missing),
            source_repository=source_repo, evidence_repository=evidence_repo,
            runner=runner, max_rounds=1, max_attempts_per_gap=1,
        )
        budget = _lowcost_budget()
        for _ in range(6):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)
        with execution_budget_scope(budget):
            result = service.assess_and_apply(context)
        self.assertEqual(runner.need_ids, ["in-1", "in-2"])
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(budget.stage_calls("evidence"), 8)
        self.assertEqual(len(evidence_repo.list_for_project(context.project.id,
                         workflow_run_id=context.workflow_run.id)), 0)

    def test_sufficient_needs_skip_continuation(self) -> None:
        design = _single_need_design()
        context = _context(design=design)
        evidence_repo = InMemoryEvidenceRepository()
        _seed_evidence(evidence_repo, context, need_id="in-1",
                       research_question_id="rq-1", evidence_id="sufficient")
        sufficient = _result_for_needs(_need_assessment(
            need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.SUFFICIENT,
        ))
        runner = _BudgetedEmptyRunner()
        result = _build_service(StaticSufficiencyEvaluator(sufficient),
                                evidence_repository=evidence_repo,
                                runner=runner).assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(runner.need_ids, [])


if __name__ == "__main__":
    unittest.main()
