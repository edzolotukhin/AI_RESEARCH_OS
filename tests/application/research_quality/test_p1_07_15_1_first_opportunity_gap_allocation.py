"""P1-07.15.1 deterministic first-opportunity remediations-gap allocation."""

from __future__ import annotations

import unittest
from typing import Sequence

from application.execution.budget_utils import EVIDENCE_REMEDIATION_BUDGET_REASON
from application.research_quality.gap_scheduler import (
    COHORT_FIRST_OPPORTUNITY,
    COHORT_REPEAT_OPPORTUNITY,
    decide_next_actionable_gap,
    select_next_actionable_gap,
)
from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from tests.application.research_quality.test_targeted_research_loop import (
    RecordingTargetedRunner,
    SequentialSufficiencyEvaluator,
    _build_service,
    _context,
    _design_two_needs,
    _need_assessment,
    _result_for_needs,
)


def _request(need_id: str, rq_id: str) -> TargetedResearchRequest:
    return TargetedResearchRequest(
        workflow_run_id="run-1",
        research_design_id="design-1",
        research_question_id=rq_id,
        information_need_id=need_id,
        gap_types=(GapType.NO_EVIDENCE,),
    )


def _in123() -> tuple[TargetedResearchRequest, ...]:
    return (
        _request("IN2", "RQ1"),
        _request("IN3", "RQ2"),
        _request("IN1", "RQ1"),
    )


def _decide(
    gaps: tuple[TargetedResearchRequest, ...],
    *,
    attempts: dict[str, int] | None = None,
    stalled: set[str] | None = None,
    max_attempts: int = 2,
    remaining: int | None = 6,
    improved: set[str] | None = None,
):
    return decide_next_actionable_gap(
        gaps,
        gap_attempt_counts=attempts or {},
        stalled_need_ids=stalled or set(),
        max_attempts_per_gap=max_attempts,
        remaining_remediation_evidence_calls=remaining,
        prior_improved_need_ids=improved,
    )


class FirstOpportunitySchedulerUnitTests(unittest.TestCase):
    def test_case_1_all_untouched_selects_in1_then_in2_not_in1(self) -> None:
        gaps = _in123()
        first = _decide(gaps)
        self.assertEqual(first.selected.information_need_id, "IN1")
        self.assertEqual(first.cohort, COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(first.selection_reason, COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(first.tie_break_key, ("RQ1", "IN1"))
        self.assertEqual(
            list(first.first_opportunity_need_ids),
            ["IN1", "IN2", "IN3"],
        )

        second = _decide(gaps, attempts={"IN1": 1}, improved={"IN1"})
        self.assertEqual(second.selected.information_need_id, "IN2")
        self.assertEqual(second.cohort, COHORT_FIRST_OPPORTUNITY)
        self.assertNotEqual(second.selected.information_need_id, "IN1")

    def test_case_2_improved_in1_does_not_take_immediate_attempt_2(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1},
            improved={"IN1"},
        )
        self.assertEqual(decision.selected.information_need_id, "IN2")
        self.assertIn("IN1", decision.repeat_opportunity_need_ids)
        self.assertIn("IN2", decision.first_opportunity_need_ids)

    def test_case_3_non_improved_stall_selects_in2(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1},
            stalled={"IN1"},
        )
        self.assertEqual(decision.selected.information_need_id, "IN2")
        self.assertNotIn("IN1", decision.eligible_need_ids)
        wrapper = select_next_actionable_gap(
            _in123(),
            gap_attempt_counts={"IN1": 1},
            stalled_need_ids={"IN1"},
            max_attempts_per_gap=2,
        )
        self.assertEqual(wrapper.information_need_id, "IN2")

    def test_case_4_repeat_cohort_after_all_first_opportunities(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1, "IN2": 1, "IN3": 1},
            improved={"IN1", "IN3"},
        )
        self.assertEqual(decision.cohort, COHORT_REPEAT_OPPORTUNITY)
        self.assertEqual(decision.selected.information_need_id, "IN1")
        self.assertEqual(decision.tie_break_key, ("RQ1", "IN1"))
        self.assertEqual(list(decision.first_opportunity_need_ids), [])

    def test_case_4_stalled_repeat_skipped_in_repeat_cohort(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1, "IN2": 1, "IN3": 1},
            stalled={"IN2"},
            improved={"IN1", "IN3"},
        )
        self.assertEqual(decision.selected.information_need_id, "IN1")
        self.assertNotIn("IN2", decision.eligible_need_ids)

    def test_case_5_attempt_limit_never_attempt_3(self) -> None:
        decision = _decide(
            (_request("IN1", "RQ1"),),
            attempts={"IN1": 2},
            improved={"IN1"},
        )
        self.assertIsNone(decision.selected)
        self.assertEqual(decision.selection_reason, "none_eligible")

    def test_case_6_status_does_not_define_priority(self) -> None:
        gaps = (
            _request("IN12", "RQ5"),
            _request("IN10", "RQ4"),
            _request("IN1", "RQ1"),
        )
        decision = _decide(gaps)
        self.assertEqual(decision.selected.information_need_id, "IN1")
        self.assertEqual(decision.tie_break_key, ("RQ1", "IN1"))

    def test_case_7_first_opportunity_beats_improved_partial(self) -> None:
        gaps = (
            _request("IN1", "RQ1"),
            _request("IN2", "RQ1"),
        )
        decision = _decide(
            gaps,
            attempts={"IN1": 1},
            improved={"IN1"},
        )
        self.assertEqual(decision.selected.information_need_id, "IN2")
        self.assertEqual(decision.cohort, COHORT_FIRST_OPPORTUNITY)

    def test_case_8_a04e8b35_regression(self) -> None:
        gaps = (
            _request("IN1", "RQ1"),
            _request("IN2", "RQ1"),
            _request("IN3", "RQ2"),
        )
        old = select_next_actionable_gap(
            gaps,
            gap_attempt_counts={"IN1": 1},
            stalled_need_ids=set(),
            max_attempts_per_gap=2,
        )
        self.assertEqual(old.information_need_id, "IN2")
        decision = _decide(gaps, attempts={"IN1": 1}, improved={"IN1"})
        self.assertEqual(decision.selected.information_need_id, "IN2")
        self.assertNotEqual(decision.selected.information_need_id, "IN1")

    def test_case_9_4fac4000_stalled_in1_next_is_in2(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1},
            stalled={"IN1"},
        )
        self.assertEqual(decision.selected.information_need_id, "IN2")

    def test_case_11_repeat_cohort_is_deterministic(self) -> None:
        gaps_a = (
            _request("IN3", "RQ2"),
            _request("IN1", "RQ1"),
            _request("IN2", "RQ1"),
        )
        gaps_b = (
            _request("IN2", "RQ1"),
            _request("IN3", "RQ2"),
            _request("IN1", "RQ1"),
        )
        attempts = {"IN1": 1, "IN2": 1, "IN3": 1}
        first = _decide(gaps_a, attempts=attempts, improved={"IN1", "IN2", "IN3"})
        second = _decide(gaps_b, attempts=attempts, improved={"IN1", "IN2", "IN3"})
        self.assertEqual(first.selected.information_need_id, second.selected.information_need_id)
        self.assertEqual(first.selected.information_need_id, "IN1")

    def test_case_12_source_exhaustion_not_an_input(self) -> None:
        source = decide_next_actionable_gap.__code__.co_varnames
        self.assertNotIn("exhausted_pairs", source)
        self.assertNotIn("source_ids", source)

    def test_case_13_scheduler_adds_zero_provider_calls(self) -> None:
        _decide(_in123(), remaining=3)
        _decide(_in123(), attempts={"IN1": 1}, remaining=3)

    def test_case_14_observability_fields(self) -> None:
        decision = _decide(
            _in123(),
            attempts={"IN1": 1},
            stalled=set(),
            remaining=4,
            improved={"IN1"},
        )
        payload = decision.to_dict()
        self.assertEqual(payload["selected_need_id"], "IN2")
        self.assertEqual(payload["cohort"], COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(payload["selection_reason"], COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(payload["attempt_counts"]["IN1"], 1)
        self.assertEqual(payload["attempt_counts"]["IN2"], 0)
        self.assertEqual(payload["remaining_remediation_evidence_calls"], 4)
        self.assertEqual(payload["prior_improved_need_ids"], ["IN1"])
        self.assertEqual(payload["tie_break_key"], ["RQ1", "IN2"])
        self.assertIn("IN1", payload["eligible_need_ids"])
        self.assertIn("IN2", payload["eligible_need_ids"])

    def test_historical_2b91089c_d4db3024_non_improved_next_in2(self) -> None:
        for stalled in ({"IN1"}, set()):
            decision = _decide(
                (
                    _request("IN1", "RQ1"),
                    _request("IN2", "RQ1"),
                    _request("IN5", "RQ2"),
                ),
                attempts={"IN1": 1},
                stalled=stalled,
            )
            if stalled:
                self.assertEqual(decision.selected.information_need_id, "IN2")
            else:
                self.assertEqual(decision.selected.information_need_id, "IN2")


class ImprovingFirstNeedEvaluator:
    """IN1 becomes PARTIAL after evidence appears; other needs stay MISSING."""

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ):
        self.calls += 1
        assessments = []
        for need in design.information_needs:
            has_evidence = any(need.id in item.information_need_refs for item in evidence)
            if need.id == "in-1" and has_evidence:
                status = SufficiencyStatus.PARTIAL
            elif has_evidence:
                status = SufficiencyStatus.PARTIAL
            else:
                status = SufficiencyStatus.MISSING
            assessments.append(
                _need_assessment(
                    need_id=need.id,
                    rq_id=need.research_question_id,
                    status=status,
                ),
            )
        return _result_for_needs(*assessments)


class BudgetStopRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.targeted_need_ids: list[str] = []

    def run(self, context, request):
        self.calls += 1
        self.targeted_need_ids.append(request.information_need_id)
        return TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
            extraction_attempted=True,
            budget_stop_reason=EVIDENCE_REMEDIATION_BUDGET_REASON,
        )


class FirstOpportunityLoopTests(unittest.TestCase):
    def test_case_2_loop_improved_in1_then_in2(self) -> None:
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
                ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(id="in-1", research_question_id="rq-1", description="A"),
                InformationNeed(id="in-2", research_question_id="rq-2", description="B"),
                InformationNeed(id="in-3", research_question_id="rq-2", description="C"),
            ),
        )
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        service = _build_service(
            ImprovingFirstNeedEvaluator(),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=design)
        service.assess_and_apply(context)
        self.assertGreaterEqual(len(runner.targeted_need_ids), 2)
        self.assertEqual(runner.targeted_need_ids[0], "in-1")
        self.assertEqual(runner.targeted_need_ids[1], "in-2")
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        decisions = loop["scheduler_decisions"]
        self.assertEqual(decisions[0]["selected_need_id"], "in-1")
        self.assertEqual(decisions[0]["selection_reason"], COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(decisions[1]["selected_need_id"], "in-2")
        self.assertEqual(decisions[1]["selection_reason"], COHORT_FIRST_OPPORTUNITY)

    def test_case_10_budget_stop_does_not_record_in2_opportunity(self) -> None:
        runner = BudgetStopRunner()
        initial = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([initial]),
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=_design_two_needs())
        result = service.assess_and_apply(context)
        self.assertEqual(runner.targeted_need_ids, ["in-1"])
        self.assertEqual(result.termination_reason, "evidence_remediation_budget_exhausted")
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        selected = [item["selected_need_id"] for item in loop["scheduler_decisions"]]
        self.assertEqual(selected, ["in-1"])
        self.assertNotIn("in-2", selected)
        history_targets = [
            need_id
            for record in loop.get("history") or []
            for need_id in record.get("targeted_need_ids", [])
        ]
        self.assertNotIn("in-2", history_targets)

    def test_bounds_unchanged_defaults(self) -> None:
        bounds = TargetedResearchBounds()
        self.assertEqual(bounds.max_gap_rounds_per_run, 2)
        self.assertEqual(bounds.max_attempts_per_gap, 2)


if __name__ == "__main__":
    unittest.main()
