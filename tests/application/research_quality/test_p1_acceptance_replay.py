"""P1 acceptance replay — end-to-end offline RQCL validation."""

from __future__ import annotations

from dataclasses import replace

import unittest

from application.execution.execution_budget_context import (
    ensure_run_budget,
    finalize_run_budget,
    get_execution_budget,
    set_execution_stage,
)
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.runtime.interrupted_task_recovery import recover_interrupted_running_tasks
from application.runtime.task_result_codec import (
    capture_task_progress,
    is_progress_checkpoint,
    restore_runtime_state,
)
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus

from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from tests.application.research_quality.p1_acceptance_replay_support import (
    IN_RQ1_MISSING,
    IN_RQ1_PARTIAL,
    IN_RQ1_SUFFICIENT,
    IN_RQ2_BLOCKED,
    IN_RQ2_INSUFFICIENT,
    IN_RQ2_SUFFICIENT,
    P1AcceptanceScorecard,
    SERBIA_INITIAL_STATUSES,
    EvidenceProgressionEvaluator,
    RecordingTargetedRunner,
    build_hybrid_evaluator,
    build_readiness_service,
    build_scorecard,
    capture_results_dto,
    full_acceptance_design,
    gap_starvation_design,
    need_assessment,
    ready_scenario_design,
    result_for_needs,
    run_rqcl_workflow,
    seed_initial_status_evidence,
    serbia_microgreens_design,
    task_statuses,
    workflow_context_for_design,
)
from tests.application.research_quality.test_targeted_research_loop import (
    StaticSufficiencyEvaluator,
)


class P1AcceptanceReplayTests(unittest.TestCase):
    """Full RQCL acceptance replay with deterministic offline providers."""

    def setUp(self) -> None:
        consume_llm_call_retry_flag()

    def test_ready_scenario_end_to_end(self) -> None:
        design = ready_scenario_design()
        initial_statuses = {
            IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_MISSING: SufficiencyStatus.MISSING,
            IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
            IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
            IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
        }
        improvable = frozenset(
            {IN_RQ1_MISSING, IN_RQ1_PARTIAL, IN_RQ2_INSUFFICIENT},
        )
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=initial_statuses,
            improvable_needs=improvable,
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
            max_attempts_per_gap=2,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(evidence_repo, context, initial_statuses)
        analysis, context = run_rqcl_workflow(context, readiness_service=service)

        scorecard = build_scorecard(
            scenario="READY",
            context=context,
            runner=runner,
            analysis_calls=analysis.calls,
            source_repo=source_repo,
            evidence_repo=evidence_repo,
        )

        self.assertTrue(scorecard.final_ready_for_analysis)
        self.assertEqual(
            scorecard.final_research_outcome,
            ResearchOutcome.READY_FOR_ANALYSIS.value,
        )
        self.assertEqual(scorecard.analysis_calls, 1)
        self.assertFalse(scorecard.technical_failure)
        self.assertFalse(scorecard.repeated_completed_iterations)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(task_statuses(context)["task-analyze"], TaskStatus.COMPLETED)
        self.assertEqual(task_statuses(context)["task-write-report"], TaskStatus.COMPLETED)
        self.assertEqual(task_statuses(context)["task-review-report"], TaskStatus.COMPLETED)

        targeted_set = set(runner.targeted_need_ids)
        self.assertIn(IN_RQ1_MISSING, targeted_set)
        self.assertIn(IN_RQ1_PARTIAL, targeted_set)
        self.assertIn(IN_RQ2_INSUFFICIENT, targeted_set)
        self.assertNotIn(IN_RQ1_SUFFICIENT, targeted_set)
        self.assertNotIn(IN_RQ2_SUFFICIENT, targeted_set)

        for need_id in improvable:
            self.assertEqual(runner.targeted_need_ids.count(need_id), 1)

        evidence = evidence_repo.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertGreaterEqual(len(evidence), 3)
        for item in evidence:
            self.assertEqual(item.workflow_run_id, context.workflow_run.id)
            self.assertEqual(item.research_design_id, design.id)

        self.assertTrue(scorecard.final_ready_for_analysis)
        self.assertEqual(scorecard.analysis_calls, 1)
        self.assertFalse(scorecard.technical_failure)

    def test_insufficient_research_scenario_end_to_end(self) -> None:
        design = full_acceptance_design()
        initial_statuses = {
            IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_MISSING: SufficiencyStatus.MISSING,
            IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
            IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
            IN_RQ2_BLOCKED: SufficiencyStatus.BLOCKED,
            IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
        }
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=initial_statuses,
            improvable_needs=frozenset({IN_RQ1_PARTIAL}),
            stuck_needs=frozenset({IN_RQ1_MISSING, IN_RQ2_INSUFFICIENT}),
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
            max_attempts_per_gap=2,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(evidence_repo, context, initial_statuses)
        analysis, context = run_rqcl_workflow(context, readiness_service=service)
        scorecard = build_scorecard(
            scenario="INSUFFICIENT_RESEARCH",
            context=context,
            runner=runner,
            analysis_calls=analysis.calls,
            source_repo=source_repo,
            evidence_repo=evidence_repo,
        )

        readiness = context.read_shared("research_readiness")
        self.assertFalse(scorecard.final_ready_for_analysis)
        self.assertEqual(
            scorecard.final_research_outcome,
            ResearchOutcome.INSUFFICIENT_RESEARCH.value,
        )
        self.assertEqual(scorecard.analysis_calls, 0)
        self.assertFalse(scorecard.technical_failure)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(task_statuses(context)["task-analyze"], TaskStatus.SKIPPED)
        self.assertEqual(task_statuses(context)["task-write-report"], TaskStatus.SKIPPED)
        self.assertEqual(task_statuses(context)["task-review-report"], TaskStatus.SKIPPED)
        self.assertIn(
            scorecard.termination_reason,
            {"no_material_improvement", "max_research_rounds"},
        )
        self.assertIn(IN_RQ2_BLOCKED, readiness["blocking_information_need_ids"])
        self.assertFalse(scorecard.final_ready_for_analysis)
        self.assertEqual(scorecard.analysis_calls, 0)
        self.assertFalse(scorecard.technical_failure)

    def test_gap_starvation_three_actionable_gaps(self) -> None:
        design = gap_starvation_design()
        all_missing = result_for_needs(
            need_assessment(
                need_id="in-1",
                rq_id="rq-1",
                status=SufficiencyStatus.MISSING,
            ),
            need_assessment(
                need_id="in-2",
                rq_id="rq-2",
                status=SufficiencyStatus.PARTIAL,
            ),
            need_assessment(
                need_id="in-3",
                rq_id="rq-3",
                status=SufficiencyStatus.INSUFFICIENT,
            ),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = build_readiness_service(
            StaticSufficiencyEvaluator(all_missing),
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        context = workflow_context_for_design(design)
        service.assess_and_apply(context)

        self.assertEqual(runner.targeted_need_ids, ["in-1", "in-2", "in-3"])
        readiness = context.read_shared("research_readiness")
        self.assertEqual(
            readiness["research_loop_termination_reason"],
            "no_material_improvement",
        )
        self.assertEqual(len(readiness["research_loop_history"]), 3)
        self.assertFalse(readiness["ready_for_analysis"])

    def test_blocked_need_never_targeted(self) -> None:
        design = full_acceptance_design()
        mixed = result_for_needs(
            need_assessment(
                need_id=IN_RQ2_BLOCKED,
                rq_id="rq-competition",
                status=SufficiencyStatus.BLOCKED,
            ),
            need_assessment(
                need_id=IN_RQ1_MISSING,
                rq_id="rq-market",
                status=SufficiencyStatus.MISSING,
            ),
            need_assessment(
                need_id=IN_RQ1_SUFFICIENT,
                rq_id="rq-market",
                status=SufficiencyStatus.SUFFICIENT,
            ),
            need_assessment(
                need_id=IN_RQ2_SUFFICIENT,
                rq_id="rq-competition",
                status=SufficiencyStatus.SUFFICIENT,
            ),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = build_readiness_service(
            StaticSufficiencyEvaluator(mixed),
            runner=runner,
            max_rounds=1,
        )
        context = workflow_context_for_design(design)
        result = service.assess_and_apply(context)

        self.assertEqual(runner.targeted_need_ids, [IN_RQ1_MISSING])
        self.assertNotIn(IN_RQ2_BLOCKED, runner.targeted_need_ids)
        self.assertIn(IN_RQ2_BLOCKED, result.blocking_information_need_ids)

    def test_blocked_only_outcome_is_insufficient_not_technical_failure(self) -> None:
        full_design = full_acceptance_design()
        included_need_ids = {
            IN_RQ1_SUFFICIENT,
            IN_RQ2_BLOCKED,
            IN_RQ2_SUFFICIENT,
        }
        design = replace(
            full_design,
            information_needs=tuple(
                need
                for need in full_design.information_needs
                if need.id in included_need_ids
            ),
        )
        blocked_only = result_for_needs(
            need_assessment(
                need_id=IN_RQ1_SUFFICIENT,
                rq_id="rq-market",
                status=SufficiencyStatus.SUFFICIENT,
            ),
            need_assessment(
                need_id=IN_RQ2_BLOCKED,
                rq_id="rq-competition",
                status=SufficiencyStatus.BLOCKED,
            ),
            need_assessment(
                need_id=IN_RQ2_SUFFICIENT,
                rq_id="rq-competition",
                status=SufficiencyStatus.SUFFICIENT,
            ),
        )
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        service = build_readiness_service(
            StaticSufficiencyEvaluator(blocked_only),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(
            evidence_repo,
            context,
            {
                IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
                IN_RQ2_BLOCKED: SufficiencyStatus.BLOCKED,
                IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            },
        )
        analysis, context = run_rqcl_workflow(context, readiness_service=service)

        self.assertEqual(runner.calls, 0)
        readiness = context.read_shared("research_readiness")
        self.assertFalse(readiness["ready_for_analysis"])
        self.assertEqual(readiness["research_outcome"], ResearchOutcome.INSUFFICIENT_RESEARCH.value)
        self.assertEqual(readiness.get("termination_reason"), "blocked_gaps")
        self.assertEqual(analysis.calls, 0)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)

    def test_cross_need_isolation(self) -> None:
        design = ready_scenario_design()
        initial_statuses = {
            IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_MISSING: SufficiencyStatus.MISSING,
            IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
            IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
            IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
        }
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=initial_statuses,
            improvable_needs=frozenset({IN_RQ1_MISSING}),
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        context = workflow_context_for_design(design)
        service.assess_and_apply(context)

        evidence = evidence_repo.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertGreaterEqual(len(evidence), 1)
        missing_evidence = [
            item for item in evidence if IN_RQ1_MISSING in item.information_need_refs
        ]
        self.assertEqual(len(missing_evidence), 1)
        for item in missing_evidence:
            self.assertNotIn(IN_RQ1_PARTIAL, item.information_need_refs)
            self.assertNotIn(IN_RQ2_INSUFFICIENT, item.information_need_refs)
        self.assertIn(IN_RQ1_MISSING, runner.targeted_need_ids)

        readiness = context.read_shared("research_readiness")
        self.assertNotIn(IN_RQ1_MISSING, readiness["blocking_information_need_ids"])
        self.assertIn(IN_RQ1_PARTIAL, readiness["blocking_information_need_ids"])
        self.assertIn(IN_RQ2_INSUFFICIENT, readiness["blocking_information_need_ids"])

    def test_in_memory_interrupt_recovery_skips_completed_iteration(self) -> None:
        design = gap_starvation_design()
        initial = {
            "in-1": SufficiencyStatus.MISSING,
            "in-2": SufficiencyStatus.PARTIAL,
            "in-3": SufficiencyStatus.INSUFFICIENT,
        }
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            crash_before_need_id="in-2",
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=initial,
            improvable_needs=frozenset({"in-1", "in-2", "in-3"}),
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
            max_attempts_per_gap=1,
        )
        context = workflow_context_for_design(design)
        readiness_task = next(
            task
            for task in context.workflow_run.tasks
            if task.definition_id == "task-assess-research-readiness"
        )
        readiness_task.ready()
        readiness_task.start()
        context.current_task = readiness_task
        context.workflow_run.ready()
        context.workflow_run.start()

        with self.assertRaises(RuntimeError):
            service.assess_and_apply(context)

        progress = capture_task_progress(context, readiness_task.id)
        self.assertTrue(is_progress_checkpoint(progress))
        loop_state = progress["shared_state"][SHARED_LOOP_STATE_KEY]
        self.assertEqual(loop_state["research_loop_count"], 1)
        self.assertEqual(loop_state["history"][0]["targeted_need_ids"], ["in-1"])
        self.assertEqual(runner.targeted_need_ids.count("in-1"), 1)

        recover_interrupted_running_tasks(
            context.workflow_run,
            {readiness_task.id: progress},
        )
        self.assertEqual(readiness_task.status, TaskStatus.READY)
        restore_runtime_state(context, {readiness_task.id: progress})
        readiness_task.start()

        resume_runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        resume_service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=resume_runner,
            max_rounds=2,
            max_attempts_per_gap=1,
        )
        resume_service.assess_and_apply(context)

        self.assertEqual(runner.targeted_need_ids.count("in-1"), 1)
        self.assertIn("in-2", resume_runner.targeted_need_ids)

    def test_budget_and_telemetry(self) -> None:
        design = ready_scenario_design()
        semantic_statuses = {
            IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_MISSING: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_PARTIAL: SufficiencyStatus.SUFFICIENT,
            IN_RQ2_INSUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
        }
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        progression = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses={
                IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
                IN_RQ1_MISSING: SufficiencyStatus.MISSING,
                IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
                IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
                IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            },
            improvable_needs=frozenset(
                {IN_RQ1_MISSING, IN_RQ1_PARTIAL, IN_RQ2_INSUFFICIENT},
            ),
        )
        service = build_readiness_service(
            progression,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(
            evidence_repo,
            context,
            progression._initial_statuses,
        )
        ensure_run_budget(context)
        set_execution_stage("sufficiency")
        service.assess_and_apply(context)
        finalize_run_budget(context)

        readiness = context.read_shared("research_readiness")
        summary = context.shared_state.get("run_usage_summary")
        self.assertIsNotNone(summary)
        self.assertGreaterEqual(readiness["research_loop_count"], 1)
        self.assertFalse(consume_llm_call_retry_flag())

        hybrid, semantic = build_hybrid_evaluator(
            design=design,
            semantic_statuses=semantic_statuses,
        )
        seeded = evidence_repo.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        self.assertGreaterEqual(len(seeded), 1)
        ensure_run_budget(context)
        set_execution_stage("sufficiency")
        hybrid.evaluate(design=design, evidence=seeded[:1])
        budget = get_execution_budget()
        self.assertIsNotNone(budget)
        self.assertGreaterEqual(semantic.calls, 1)
        self.assertGreaterEqual(budget.stage_calls("sufficiency"), 1)

    def test_observability_results_dto_fields(self) -> None:
        design = ready_scenario_design()
        initial_statuses = {
            IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            IN_RQ1_MISSING: SufficiencyStatus.MISSING,
            IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
            IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
            IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
        }
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=initial_statuses,
            improvable_needs=frozenset(
                {IN_RQ1_MISSING, IN_RQ1_PARTIAL, IN_RQ2_INSUFFICIENT},
            ),
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(evidence_repo, context, initial_statuses)
        run_rqcl_workflow(context, readiness_service=service)

        dto = capture_results_dto(context)
        self.assertIsNotNone(dto["research_readiness"])
        self.assertIsNotNone(dto["research_loop_count"])
        self.assertIsNotNone(dto["research_loop_history"])
        self.assertTrue(dto["results_ready"])

        history = dto["research_loop_history"] or []
        self.assertGreaterEqual(len(history), 1)
        record = history[0]
        for field_name in (
            "attempt",
            "round_number",
            "blocking_need_ids_before",
            "targeted_need_ids",
            "queries_generated",
            "new_sources_count",
            "new_evidence_count",
            "readiness_after",
            "improved",
        ):
            self.assertIn(field_name, record)

        readiness = dto["research_readiness"]
        self.assertIn("termination_reason", readiness or {})
        if not readiness.get("ready_for_analysis"):
            self.assertTrue(
                readiness.get("research_loop_termination_reason")
                or readiness.get("termination_reason"),
            )

    def test_serbia_microgreens_shaped_replay_ready(self) -> None:
        design = serbia_microgreens_design()
        improvable = frozenset({"in-market-size", "in-regulatory-coverage"})
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=SERBIA_INITIAL_STATUSES,
            improvable_needs=improvable,
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(evidence_repo, context, SERBIA_INITIAL_STATUSES)
        analysis, context = run_rqcl_workflow(context, readiness_service=service)
        scorecard = build_scorecard(
            scenario="SERBIA_MICROGREENS_READY",
            context=context,
            runner=runner,
            analysis_calls=analysis.calls,
            source_repo=source_repo,
            evidence_repo=evidence_repo,
        )

        self.assertTrue(scorecard.final_ready_for_analysis)
        self.assertEqual(scorecard.analysis_calls, 1)
        targeted = set(runner.targeted_need_ids)
        self.assertIn("in-market-size", targeted)
        self.assertIn("in-regulatory-coverage", targeted)
        self.assertNotIn("in-market-maturity", targeted)
        self.assertNotIn("in-competitors", targeted)

    def test_serbia_microgreens_shaped_replay_insufficient(self) -> None:
        design = serbia_microgreens_design()
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses=SERBIA_INITIAL_STATUSES,
            improvable_needs=frozenset({"in-market-size"}),
            stuck_needs=frozenset({"in-regulatory-coverage"}),
        )
        service = build_readiness_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        context = workflow_context_for_design(design)
        seed_initial_status_evidence(evidence_repo, context, SERBIA_INITIAL_STATUSES)
        analysis, context = run_rqcl_workflow(context, readiness_service=service)

        readiness = context.read_shared("research_readiness")
        self.assertFalse(readiness["ready_for_analysis"])
        self.assertEqual(
            readiness["research_outcome"],
            ResearchOutcome.INSUFFICIENT_RESEARCH.value,
        )
        self.assertEqual(analysis.calls, 0)
        self.assertIn("in-regulatory-coverage", readiness["blocking_information_need_ids"])

    def test_acceptance_scorecard_summary(self) -> None:
        """Emit deterministic scorecards for READY and INSUFFICIENT scenarios."""
        scorecards: list[P1AcceptanceScorecard] = []

        design = ready_scenario_design()
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        ready_evaluator = EvidenceProgressionEvaluator(
            design=design,
            initial_statuses={
                IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
                IN_RQ1_MISSING: SufficiencyStatus.MISSING,
                IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
                IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
                IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
            },
            improvable_needs=frozenset(
                {IN_RQ1_MISSING, IN_RQ1_PARTIAL, IN_RQ2_INSUFFICIENT},
            ),
        )
        ready_context = workflow_context_for_design(design)
        seed_initial_status_evidence(
            evidence_repo,
            ready_context,
            ready_evaluator._initial_statuses,
        )
        ready_analysis, ready_context = run_rqcl_workflow(
            ready_context,
            readiness_service=build_readiness_service(
                ready_evaluator,
                source_repository=source_repo,
                evidence_repository=evidence_repo,
                runner=runner,
            ),
        )
        scorecards.append(
            build_scorecard(
                scenario="READY",
                context=ready_context,
                runner=runner,
                analysis_calls=ready_analysis.calls,
                source_repo=source_repo,
                evidence_repo=evidence_repo,
            ),
        )

        insuf_design = full_acceptance_design()
        insuf_runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        insuf_context = workflow_context_for_design(insuf_design)
        insuf_analysis, insuf_context = run_rqcl_workflow(
            insuf_context,
            readiness_service=build_readiness_service(
                EvidenceProgressionEvaluator(
                    design=insuf_design,
                    initial_statuses={
                        IN_RQ1_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
                        IN_RQ1_MISSING: SufficiencyStatus.MISSING,
                        IN_RQ1_PARTIAL: SufficiencyStatus.PARTIAL,
                        IN_RQ2_INSUFFICIENT: SufficiencyStatus.INSUFFICIENT,
                        IN_RQ2_BLOCKED: SufficiencyStatus.BLOCKED,
                        IN_RQ2_SUFFICIENT: SufficiencyStatus.SUFFICIENT,
                    },
                    improvable_needs=frozenset(),
                    stuck_needs=frozenset(
                        {IN_RQ1_MISSING, IN_RQ1_PARTIAL, IN_RQ2_INSUFFICIENT},
                    ),
                ),
                runner=insuf_runner,
                max_rounds=1,
            ),
        )
        scorecards.append(
            build_scorecard(
                scenario="INSUFFICIENT_RESEARCH",
                context=insuf_context,
                runner=insuf_runner,
                analysis_calls=insuf_analysis.calls,
                source_repo=InMemorySourceRepository(),
                evidence_repo=InMemoryEvidenceRepository(),
            ),
        )

        reports = [card.to_report() for card in scorecards]
        self.assertTrue(reports[0]["final_ready_for_analysis"])
        self.assertEqual(reports[0]["analysis_calls"], 1)
        self.assertFalse(reports[0]["technical_failure"])
        self.assertFalse(reports[1]["final_ready_for_analysis"])
        self.assertEqual(reports[1]["analysis_calls"], 0)
        self.assertFalse(reports[1]["technical_failure"])


if __name__ == "__main__":
    unittest.main()
