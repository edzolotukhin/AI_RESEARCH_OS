from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.analysis.analysis_coverage_service import AnalysisCoverageResult
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.runtime.task_result_codec import capture_task_result, restore_runtime_state
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _h3_template() -> WorkflowTemplate:
    return WorkflowTemplate(
        id="template-1",
        name="H3",
        task_definitions=[
            SimpleNamespace(id="task-review-report-1"),
            SimpleNamespace(id="task-revise-report"),
            SimpleNamespace(id="task-review-report-2"),
        ],
        research_design_snapshot=SimpleNamespace(id="design-1", information_needs=()),
        research_brief_snapshot=None,
    )


class _AnalysisExecutor:
    def run(self, context: WorkflowContext) -> WorkflowContext:
        context.write_shared("research_readiness", {"ready_for_analysis": True})
        if context.workflow_template is not None and context.workflow_template.name == "H3":
            context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
        return context


class _RecordingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        assert context.current_task is not None
        self.executed.append(context.current_task.definition_id)
        return context


class _FailingAnalysisExecutor:
    def run(self, context: WorkflowContext) -> WorkflowContext:
        raise RuntimeError("provider failure")


class AnalysisCoverageGateTests(unittest.TestCase):
    def _engine(self, executor):
        resolver = Mock()
        resolver.resolve.side_effect = lambda task: (
            _AnalysisExecutor()
            if task.definition_id == "task-analyze"
            else executor
        )
        lifecycle = TaskLifecycleManager()
        return WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(resolver=resolver, lifecycle=lifecycle),
            completion_policy=WorkflowCompletionPolicy(),
            finding_repository=Mock(),
            evidence_repository=Mock(),
            source_repository=Mock(),
        )

    def _run(self, coverage: AnalysisCoverageResult):
        recorder = _RecordingExecutor()
        engine = self._engine(recorder)
        run = make_workflow_run(
            make_task("task-analyze"),
            make_task("task-write-report", depends_on=["task-analyze"]),
            make_task("task-review-report-1", depends_on=["task-write-report"]),
            make_task("task-revise-report", depends_on=["task-review-report-1"]),
            make_task("task-review-report-2", depends_on=["task-revise-report"]),
            make_task("task-finalize-deliverables", depends_on=["task-review-report-2"]),
        )
        engine._finding_repository.list_for_project.return_value = ()
        engine._evidence_repository.list_for_project.return_value = ()
        context = WorkflowContext(
            project=Project(id="p1", name="Project"),
            workflow_template=_h3_template(),
            workflow_run=run,
        )
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
        resolver_result = (
            ("INSUFFICIENT", ("in-2",))
            if not coverage.fully_covered else ("COMPLETED", ())
        )
        with patch("application.workflow_engine.assess_analysis_coverage", return_value=coverage), \
             patch("application.workflow_engine.derive_authoritative_outcome", return_value=resolver_result):
            result = engine.run(context)
        return result, recorder

    def test_incomplete_coverage_skips_h3_report_branch_and_persists_exact_ids(self):
        coverage = AnalysisCoverageResult(
            required_information_need_ids=("in-1", "in-2"),
            covered_information_need_ids=("in-1",),
            missing_information_need_ids=("in-2",),
            evidence_without_finding=("ev-2",),
            fully_covered=False,
        )
        result, recorder = self._run(coverage)

        self.assertEqual(recorder.executed, [])
        self.assertEqual(result.workflow_run.tasks[0].status, TaskStatus.COMPLETED)
        self.assertTrue(all(task.status == TaskStatus.SKIPPED for task in result.workflow_run.tasks[1:]))
        self.assertEqual(result.shared_state["analysis_coverage"], coverage.to_dict())
        self.assertEqual(
            result.shared_state["research_product_outcome"]["unresolved_information_need_ids"],
            ["in-2"],
        )
        result.current_task = result.workflow_run.tasks[0]
        snapshot = capture_task_result(result, "analysis-task")
        fresh = WorkflowContext(
            project=result.project,
            workflow_template=result.workflow_template,
            workflow_run=result.workflow_run,
        )
        restore_runtime_state(fresh, {result.workflow_run.tasks[0].id: snapshot})
        self.assertEqual(fresh.shared_state["analysis_coverage"], coverage.to_dict())

    def test_complete_coverage_preserves_normal_report_path(self):
        coverage = AnalysisCoverageResult(
            required_information_need_ids=("in-1",),
            covered_information_need_ids=("in-1",),
            missing_information_need_ids=(),
            evidence_without_finding=(),
            fully_covered=True,
        )
        result, recorder = self._run(coverage)

        self.assertEqual(
            recorder.executed,
            [
                "task-write-report",
                "task-review-report-1",
                "task-revise-report",
                "task-review-report-2",
                "task-finalize-deliverables",
            ],
        )
        self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in result.workflow_run.tasks))
        self.assertEqual(result.shared_state["analysis_coverage"], coverage.to_dict())

    def test_legacy_workflow_does_not_invoke_coverage_gate(self):
        recorder = _RecordingExecutor()
        engine = self._engine(recorder)
        run = make_workflow_run(make_task("task-analyze"), make_task("task-write-report", depends_on=["task-analyze"]))
        engine._finding_repository.list_for_project.return_value = ()
        engine._evidence_repository.list_for_project.return_value = ()
        context = WorkflowContext(
            project=Project(id="p1", name="Project"),
            workflow_template=WorkflowTemplate(id="legacy", name="Legacy", research_design_snapshot=SimpleNamespace(id="d", information_needs=())),
            workflow_run=run,
        )
        with patch("application.workflow_engine.assess_analysis_coverage") as assess:
            engine.run(context)
        assess.assert_not_called()
        self.assertEqual(recorder.executed, ["task-write-report"])

    def test_technical_analysis_failure_does_not_create_methodological_gate(self):
        resolver = Mock()
        recorder = _RecordingExecutor()
        resolver.resolve.side_effect = lambda task: (
            _FailingAnalysisExecutor()
            if task.definition_id == "task-analyze"
            else recorder
        )
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(resolver=resolver, lifecycle=TaskLifecycleManager()),
            completion_policy=WorkflowCompletionPolicy(),
            finding_repository=Mock(),
            evidence_repository=Mock(),
            source_repository=Mock(),
        )
        run = make_workflow_run(make_task("task-analyze"), make_task("task-write-report", depends_on=["task-analyze"]))
        context = WorkflowContext(
            project=Project(id="p1", name="Project"),
            workflow_template=_h3_template(),
            workflow_run=run,
        )
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
        with patch("application.workflow_engine.assess_analysis_coverage") as assess:
            with self.assertRaises(RuntimeError):
                engine.run(context)
        assess.assert_not_called()
        self.assertNotIn("analysis_coverage", context.shared_state)
        self.assertEqual(context.shared_state["research_product_outcome"]["outcome"], "FAILED")


if __name__ == "__main__":
    unittest.main()
