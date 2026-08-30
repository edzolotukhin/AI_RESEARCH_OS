from __future__ import annotations

import unittest

from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class _Executor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, context):
        self.calls.append(context.current_task.definition_id)
        return context


class _Resolver:
    def __init__(self, calls: list[str]) -> None:
        self.executor = _Executor(calls)

    def resolve(self, task):
        return self.executor


class _Checkpoint:
    def __init__(self) -> None:
        self.running: list[str] = []

    def on_workflow_started(self, context):
        pass

    def on_scheduling(self, context, scheduling_result):
        pass

    def on_task_running(self, context):
        self.running.append(context.current_task.definition_id)

    def on_task_progress(self, context):
        pass

    def on_task_finished(self, context, *, error):
        pass

    def on_workflow_finalized(self, context, *, error):
        pass


def _run():
    weightset = make_task("quant_weightset", task_id="weightset")
    approval = make_task(
        "quant_weight_approval",
        task_id="weight-approval",
        depends_on=["quant_weightset"],
    )
    analysis = make_task(
        "quant_analysis",
        task_id="analysis",
        depends_on=["quant_weight_approval"],
    )
    run = make_workflow_run(weightset, approval, analysis, run_id="run")
    run.project_id = "project"
    return run, weightset, approval, analysis


def _engine(calls: list[str]) -> WorkflowEngine:
    return WorkflowEngine(
        TaskScheduler(),
        TaskExecutor(_Resolver(calls), TaskLifecycleManager()),
        WorkflowCompletionPolicy(),
    )


class Q213DUnweightedWorkflowOrchestrationTests(unittest.TestCase):
    def test_explicit_unweighted_skips_satisfy_analysis_dependency(self):
        run, weightset, approval, analysis = _run()
        run.skip_task_as_satisfied_dependency(weightset)
        run.skip_task_as_satisfied_dependency(approval)

        result = TaskScheduler().schedule(run)

        self.assertEqual(weightset.status, TaskStatus.SKIPPED)
        self.assertEqual(approval.status, TaskStatus.SKIPPED)
        self.assertEqual(analysis.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (analysis.id,))

    def test_ordinary_skipped_failed_and_pending_dependencies_do_not_satisfy(self):
        ordinary, skipped, _, downstream = _run()
        skipped.skip()
        TaskScheduler().schedule(ordinary)
        self.assertEqual(downstream.status, TaskStatus.SKIPPED)

        failed, _, approval, downstream = _run()
        approval.ready()
        approval.start()
        approval.fail()
        TaskScheduler().schedule(failed)
        self.assertEqual(downstream.status, TaskStatus.SKIPPED)

        pending, _, _, downstream = _run()
        TaskScheduler().schedule(pending)
        self.assertEqual(downstream.status, TaskStatus.WAITING)

    def test_rd_attempt_is_checkpointed_before_local_execution(self):
        run, weightset, approval, analysis = _run()
        run.skip_task_as_satisfied_dependency(weightset)
        run.skip_task_as_satisfied_dependency(approval)
        calls: list[str] = []
        checkpoint = _Checkpoint()
        context = WorkflowContext(
            project=Project(id="project", name="Project"),
            workflow_run=run,
        )

        _engine(calls).run(context, checkpoint=checkpoint)

        self.assertEqual(checkpoint.running, ["quant_analysis"])
        self.assertEqual(calls, ["quant_analysis"])
        self.assertEqual(analysis.status, TaskStatus.COMPLETED)
        self.assertTrue(run.is_terminal)

    def test_restart_preserves_satisfied_skips_and_rd_runs_once(self):
        run, weightset, approval, analysis = _run()
        run.skip_task_as_satisfied_dependency(weightset)
        run.skip_task_as_satisfied_dependency(approval)
        run.ready()
        run.start()
        repository = InMemoryWorkflowRunRepository()
        repository.create(run, project_id="project")

        reloaded = repository.get_by_id(run.id)
        self.assertEqual(
            reloaded.satisfied_skipped_task_ids,
            {weightset.id, approval.id},
        )
        calls: list[str] = []
        context = WorkflowContext(
            project=Project(id="project", name="Project"),
            workflow_run=reloaded,
        )
        engine = _engine(calls)
        engine.run(context)
        engine.run(context)

        self.assertEqual(calls, ["quant_analysis"])
        self.assertEqual(
            next(task for task in reloaded.tasks if task.id == analysis.id).status,
            TaskStatus.COMPLETED,
        )


if __name__ == "__main__":
    unittest.main()
