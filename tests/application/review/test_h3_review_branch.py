from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.executors.revision_executor import RevisionExecutor, RevisionUnavailableError
from application.executors.finalization_executor import FinalizationExecutor
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H2_REPORT_CONTRACT, H3_REPORT_CONTRACT
from application.review.h3_review_branch import (
    H3ReviewBranchController, H3_REVIEW_BRANCH_KEY, H3_REVIEW_EXHAUSTED,
)
from application.review.review_service import ReviewSummary
from application.task_scheduler import TaskScheduler
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.workflow_engine import WorkflowEngine
from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from runtime.workflow_context import WorkflowContext
from tests.application.planner.test_research_design_workflow_mapper import ResearchDesignWorkflowMapperTests
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _summary(verdict: str, review_id: str = "review-1") -> ReviewSummary:
    return ReviewSummary(review_id, verdict, "report-1", None, 1, 0, 0)


def _context(*, current: str) -> WorkflowContext:
    tasks = (
        make_task("report", executor_id="report", task_id="report", status=TaskStatus.COMPLETED),
        make_task("task-review-report-1", executor_id="review", task_id="r1", depends_on=["report"], status=TaskStatus.RUNNING if current == "r1" else TaskStatus.COMPLETED),
        make_task("task-revise-report", executor_id="revision", task_id="revision", depends_on=["task-review-report-1"], status=TaskStatus.COMPLETED if current == "r2" else TaskStatus.CREATED),
        make_task("task-review-report-2", executor_id="review", task_id="r2", depends_on=["task-revise-report"], status=TaskStatus.RUNNING if current == "r2" else TaskStatus.CREATED),
        make_task("task-finalize-deliverables", executor_id="finalization", task_id="final", depends_on=["task-review-report-1", "task-revise-report", "task-review-report-2"]),
    )
    run = make_workflow_run(*tasks)
    run.ready(); run.start()
    context = WorkflowContext(workflow_run=run, project=Project(id="p1", name="p1"))
    context.current_task = next(item for item in tasks if item.id == current)
    context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
    return context


class H3ReviewBranchTests(unittest.TestCase):
    def test_round_one_approve_satisfies_bypass_and_unlocks_finalization(self):
        context = _context(current="r1")
        H3ReviewBranchController().apply_review_result(context, _summary("approve"))
        context.current_task.complete()
        TaskScheduler().schedule(context.workflow_run)
        by_id = {item.id: item for item in context.workflow_run.tasks}
        self.assertEqual(TaskStatus.SKIPPED, by_id["revision"].status)
        self.assertEqual(TaskStatus.SKIPPED, by_id["r2"].status)
        self.assertEqual({"revision", "r2"}, context.workflow_run.satisfied_skipped_task_ids)
        self.assertEqual(TaskStatus.READY, by_id["final"].status)
        self.assertTrue(context.read_shared(H3_REVIEW_BRANCH_KEY)["finalization_eligible"])
        self.assertEqual("review-1", context.read_shared("review")["review_id"])

    def test_round_one_revise_keeps_revision_path_active(self):
        context = _context(current="r1")
        H3ReviewBranchController().apply_review_result(context, _summary("revise"))
        context.current_task.complete()
        TaskScheduler().schedule(context.workflow_run)
        by_id = {item.id: item for item in context.workflow_run.tasks}
        self.assertEqual(TaskStatus.READY, by_id["revision"].status)
        self.assertEqual(TaskStatus.WAITING, by_id["r2"].status)
        self.assertFalse(context.read_shared(H3_REVIEW_BRANCH_KEY)["finalization_eligible"])
        self.assertIsNone(context.read_shared("review"))

    def test_round_two_approve_selects_second_review(self):
        context = _context(current="r2")
        summary = _summary("approve", "review-2")
        H3ReviewBranchController().apply_review_result(context, summary)
        self.assertEqual("review-2", context.read_shared("review")["review_id"])
        self.assertTrue(context.read_shared(H3_REVIEW_BRANCH_KEY)["finalization_eligible"])

    def test_round_two_revise_is_controlled_failed_terminal(self):
        context = _context(current="r2")
        H3ReviewBranchController().apply_review_result(context, _summary("revise", "review-2"))
        branch = context.read_shared(H3_REVIEW_BRANCH_KEY)
        self.assertEqual(H3_REVIEW_EXHAUSTED, branch["terminal_reason"])
        self.assertFalse(branch["finalization_eligible"])
        self.assertEqual(WorkflowStatus.FAILED, context.workflow_run.status)
        final = next(item for item in context.workflow_run.tasks if item.id == "final")
        self.assertEqual(TaskStatus.SKIPPED, final.status)
        self.assertIsNone(context.read_shared("review"))

    def test_reconcile_approve_is_idempotent(self):
        context = _context(current="r1")
        context.write_shared("review_1", _summary("approve").to_dict())
        controller = H3ReviewBranchController()
        first = controller.reconcile(context)
        second = controller.reconcile(context)
        self.assertEqual(first, second)
        self.assertEqual({"revision", "r2"}, context.workflow_run.satisfied_skipped_task_ids)

    def test_reconcile_round_one_revise_preserves_revision_path(self):
        context = _context(current="r1")
        context.write_shared("review_1", _summary("revise").to_dict())
        H3ReviewBranchController().reconcile(context)
        context.current_task.complete()
        TaskScheduler().schedule(context.workflow_run)
        revision = next(item for item in context.workflow_run.tasks if item.id == "revision")
        self.assertEqual(TaskStatus.READY, revision.status)
        self.assertFalse(context.read_shared(H3_REVIEW_BRANCH_KEY)["finalization_eligible"])

    def test_reconcile_round_two_approve_restores_canonical_projection(self):
        context = _context(current="r2")
        context.write_shared("review_1", _summary("revise").to_dict())
        context.write_shared("review_2", _summary("approve", "review-2").to_dict())
        state = H3ReviewBranchController().reconcile(context)
        self.assertTrue(state["finalization_eligible"])
        self.assertEqual("review-2", context.read_shared("review")["review_id"])

    def test_reconcile_round_two_revise_restores_failed_terminal(self):
        context = _context(current="r2")
        context.write_shared("review_1", _summary("revise").to_dict())
        context.write_shared("review_2", _summary("revise", "review-2").to_dict())
        state = H3ReviewBranchController().reconcile(context)
        self.assertEqual(H3_REVIEW_EXHAUSTED, state["terminal_reason"])
        self.assertEqual(WorkflowStatus.FAILED, context.workflow_run.status)
        self.assertIsNone(context.read_shared("review"))

    def test_engine_restart_hook_restores_missing_approve_bypass(self):
        context = _context(current="r1")
        context.current_task.complete()
        context.write_shared("review_1", _summary("approve").to_dict())
        executed = []
        executor = type("Executor", (), {
            "run": lambda self, ctx: executed.append(ctx.current_task.id) or ctx,
        })()
        resolver = Mock()
        resolver.resolve.return_value = executor
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(
                resolver=resolver,
                lifecycle=TaskLifecycleManager(),
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )

        engine.run(context)

        self.assertEqual(["final"], executed)
        self.assertEqual(WorkflowStatus.COMPLETED, context.workflow_run.status)
        self.assertEqual({"revision", "r2"}, context.workflow_run.satisfied_skipped_task_ids)

    def test_reconciled_terminal_reason_is_durably_allowlisted(self):
        context = _context(current="r2")
        context.write_shared("review_2", _summary("revise", "review-2").to_dict())
        H3ReviewBranchController().reconcile(context)
        saved = {}
        workflow_service = Mock()

        def save(run, *, expected_version, task_results):
            saved.update(task_results)
            return expected_version + 1

        workflow_service.save_workflow_run.side_effect = save
        WorkflowRuntimePersister(
            workflow_service=workflow_service,
            audit=None,
            run_id=context.workflow_run.id,
        ).on_workflow_started(context)

        self.assertEqual(H3_REVIEW_EXHAUSTED, saved[H3_REVIEW_BRANCH_KEY]["terminal_reason"])
        self.assertEqual("revise", saved["review_2"]["verdict"])
        self.assertNotIn("review", saved)

    def test_revision_executor_fails_closed_without_j2_adapter(self):
        context = _context(current="r1")
        context.write_shared("review_1", _summary("revise").to_dict())
        context.current_task = next(item for item in context.workflow_run.tasks if item.id == "revision")
        with self.assertRaisesRegex(RevisionUnavailableError, "implementation_unavailable"):
            RevisionExecutor().run(context)

    def test_revision_executor_accepts_injected_provider_free_adapter(self):
        context = _context(current="r1")
        summary = _summary("revise")
        context.write_shared("review_1", summary.to_dict())
        H3ReviewBranchController().apply_review_result(context, summary)
        context.current_task.complete()
        TaskScheduler().schedule(context.workflow_run)
        context.current_task = next(item for item in context.workflow_run.tasks if item.id == "revision")
        context.current_task.start()
        service = type("Revision", (), {"revise_for_context": lambda self, ctx: {"revision_count": 1, "report_revision": 2}})()
        RevisionExecutor(service).run(context)
        context.current_task.complete()
        TaskScheduler().schedule(context.workflow_run)
        self.assertEqual(1, context.read_shared("h3_revision")["revision_count"])
        review_two = next(item for item in context.workflow_run.tasks if item.id == "r2")
        self.assertEqual(TaskStatus.READY, review_two.status)

    def test_h3_finalization_gate_blocks_before_any_side_effect(self):
        context = _context(current="r1")
        calls = []
        finalizer = type("Finalizer", (), {
            "finalize_approved_review": lambda self, **kwargs: calls.append(kwargs),
        })()
        context.write_shared("review", _summary("approve").to_dict())
        with self.assertRaisesRegex(RuntimeError, "h3_finalization_not_eligible"):
            FinalizationExecutor(finalizer).run(context)
        self.assertEqual([], calls)


class H3WorkflowTopologyTests(unittest.TestCase):
    def setUp(self):
        fixture = ResearchDesignWorkflowMapperTests()
        fixture.setUp()
        self.project, self.design = fixture.project, fixture.design

    def test_h2_graph_is_unchanged(self):
        template = ResearchDesignWorkflowMapper(desk_report_contract_version=H2_REPORT_CONTRACT).from_research_design(self.design, self.project)
        self.assertEqual(
            ["search", "evidence", "research_quality", "analysis", "report", "review", "finalization"],
            [item.executor_id for item in template.task_definitions],
        )

    def test_h3_graph_is_expanded_and_static(self):
        template = ResearchDesignWorkflowMapper(desk_report_contract_version=H3_REPORT_CONTRACT).from_research_design(self.design, self.project)
        self.assertEqual(
            ["search", "evidence", "research_quality", "analysis", "report", "review", "revision", "review", "finalization"],
            [item.executor_id for item in template.task_definitions],
        )
        by_id = {item.id: item for item in template.task_definitions}
        self.assertEqual(
            ["task-review-report-1", "task-revise-report", "task-review-report-2"],
            by_id["task-finalize-deliverables"].depends_on,
        )


if __name__ == "__main__":
    unittest.main()
