import unittest

from domain.exceptions.runtime_state_transition_error import (
    RuntimeStateTransitionError,
)
from domain.runtime.state_machine import (
    TASK_STATE_MACHINE,
    TASK_TRANSITIONS,
    WORKFLOW_RUN_STATE_MACHINE,
    WORKFLOW_RUN_TRANSITIONS,
)
from domain.task import Task
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus


def _make_task(
    status: TaskStatus = TaskStatus.CREATED,
) -> Task:
    return Task(
        id="task-1",
        definition_id="task-1",
        name="Task",
        executor_id="agent",
        executor_type=ExecutorType.AGENT,
        status=status,
    )


def _make_workflow_run(
    status: WorkflowStatus = WorkflowStatus.CREATED,
) -> WorkflowRun:
    return WorkflowRun(
        id="run-1",
        workflow_template_id="template-1",
        status=status,
    )


class WorkflowRunTransitionTableTests(unittest.TestCase):

    def test_all_documented_transitions_are_allowed(self):
        for current, targets in WORKFLOW_RUN_TRANSITIONS.items():
            for target in targets:
                self.assertTrue(
                    WORKFLOW_RUN_STATE_MACHINE.can_transition(
                        current,
                        target,
                    ),
                    f"{current} -> {target}",
                )

    def test_undocumented_transitions_are_rejected(self):
        for current in WorkflowStatus:
            for target in WorkflowStatus:
                expected = target in WORKFLOW_RUN_TRANSITIONS.get(
                    current,
                    frozenset(),
                )
                self.assertEqual(
                    WORKFLOW_RUN_STATE_MACHINE.can_transition(
                        current,
                        target,
                    ),
                    expected,
                    f"{current} -> {target}",
                )


class TaskTransitionTableTests(unittest.TestCase):

    def test_all_documented_transitions_are_allowed(self):
        for current, targets in TASK_TRANSITIONS.items():
            for target in targets:
                self.assertTrue(
                    TASK_STATE_MACHINE.can_transition(current, target),
                    f"{current} -> {target}",
                )

    def test_undocumented_transitions_are_rejected(self):
        for current in TaskStatus:
            for target in TaskStatus:
                expected = target in TASK_TRANSITIONS.get(
                    current,
                    frozenset(),
                )
                self.assertEqual(
                    TASK_STATE_MACHINE.can_transition(current, target),
                    expected,
                    f"{current} -> {target}",
                )


class WorkflowRunStateMachineTests(unittest.TestCase):

    def test_allowed_transitions(self):
        cases = [
            (WorkflowStatus.CREATED, "ready", WorkflowStatus.READY),
            (WorkflowStatus.READY, "start", WorkflowStatus.RUNNING),
            (WorkflowStatus.RUNNING, "pause", WorkflowStatus.PAUSED),
            (WorkflowStatus.PAUSED, "resume", WorkflowStatus.RUNNING),
            (WorkflowStatus.RUNNING, "complete", WorkflowStatus.COMPLETED),
            (WorkflowStatus.RUNNING, "fail", WorkflowStatus.FAILED),
        ]

        for initial, method_name, expected in cases:
            with self.subTest(initial=initial, method=method_name):
                workflow_run = _make_workflow_run(initial)
                getattr(workflow_run, method_name)()
                self.assertEqual(workflow_run.status, expected)

    def test_cancel_from_each_non_terminal_state(self):
        for status in WorkflowStatus:
            if WORKFLOW_RUN_STATE_MACHINE.is_terminal(status):
                continue

            with self.subTest(status=status):
                workflow_run = _make_workflow_run(status)

                if status == WorkflowStatus.CREATED:
                    pass
                elif status == WorkflowStatus.READY:
                    workflow_run = _make_workflow_run(WorkflowStatus.CREATED)
                    workflow_run.ready()
                elif status == WorkflowStatus.RUNNING:
                    workflow_run = _make_workflow_run(WorkflowStatus.CREATED)
                    workflow_run.ready()
                    workflow_run.start()
                elif status == WorkflowStatus.PAUSED:
                    workflow_run = _make_workflow_run(WorkflowStatus.CREATED)
                    workflow_run.ready()
                    workflow_run.start()
                    workflow_run.pause()

                workflow_run.cancel()
                self.assertEqual(
                    workflow_run.status,
                    WorkflowStatus.CANCELLED,
                )

    def test_terminal_states_have_no_exits(self):
        for status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            workflow_run = _make_workflow_run(status)

            for method_name in (
                "ready",
                "start",
                "pause",
                "resume",
                "complete",
                "fail",
                "cancel",
            ):
                with self.subTest(status=status, method=method_name):
                    with self.assertRaises(RuntimeStateTransitionError):
                        getattr(workflow_run, method_name)()

                    self.assertEqual(workflow_run.status, status)

    def test_invalid_transition_preserves_state(self):
        workflow_run = _make_workflow_run(WorkflowStatus.CREATED)

        with self.assertRaises(RuntimeStateTransitionError) as ctx:
            workflow_run.start()

        self.assertEqual(workflow_run.status, WorkflowStatus.CREATED)
        self.assertEqual(ctx.exception.current, WorkflowStatus.CREATED)
        self.assertEqual(ctx.exception.target, WorkflowStatus.RUNNING)
        self.assertEqual(ctx.exception.entity, "WorkflowRun")

    def test_resume_only_from_paused(self):
        workflow_run = _make_workflow_run(WorkflowStatus.CREATED)

        with self.assertRaises(RuntimeStateTransitionError):
            workflow_run.resume()

        self.assertEqual(workflow_run.status, WorkflowStatus.CREATED)

    def test_complete_fail_pause_only_from_running(self):
        for method_name in ("complete", "fail", "pause"):
            workflow_run = _make_workflow_run(WorkflowStatus.READY)

            with self.subTest(method=method_name):
                with self.assertRaises(RuntimeStateTransitionError):
                    getattr(workflow_run, method_name)()

                self.assertEqual(workflow_run.status, WorkflowStatus.READY)

    def test_is_terminal(self):
        self.assertFalse(
            _make_workflow_run(WorkflowStatus.RUNNING).is_terminal,
        )
        self.assertTrue(
            _make_workflow_run(WorkflowStatus.COMPLETED).is_terminal,
        )

    def test_direct_status_mutation_is_blocked(self):
        workflow_run = _make_workflow_run()

        with self.assertRaises(AttributeError):
            workflow_run.status = WorkflowStatus.RUNNING


class TaskStateMachineTests(unittest.TestCase):

    def test_allowed_transitions(self):
        cases = [
            (TaskStatus.CREATED, "schedule", TaskStatus.WAITING),
            (TaskStatus.CREATED, "ready", TaskStatus.READY),
            (TaskStatus.WAITING, "ready", TaskStatus.READY),
            (TaskStatus.READY, "start", TaskStatus.RUNNING),
            (TaskStatus.RUNNING, "pause", TaskStatus.PAUSED),
            (TaskStatus.PAUSED, "resume", TaskStatus.RUNNING),
            (TaskStatus.RUNNING, "complete", TaskStatus.COMPLETED),
            (TaskStatus.RUNNING, "fail", TaskStatus.FAILED),
        ]

        for initial, method_name, expected in cases:
            with self.subTest(initial=initial, method=method_name):
                task = _make_task(initial)
                getattr(task, method_name)()
                self.assertEqual(task.status, expected)

    def test_skip_from_allowed_states(self):
        for status in (
            TaskStatus.CREATED,
            TaskStatus.WAITING,
            TaskStatus.READY,
        ):
            with self.subTest(status=status):
                task = _make_task(status)
                task.skip()
                self.assertEqual(task.status, TaskStatus.SKIPPED)

    def test_skip_rejected_from_running(self):
        task = _make_task(TaskStatus.CREATED)
        task.ready()
        task.start()

        with self.assertRaises(RuntimeStateTransitionError):
            task.skip()

        self.assertEqual(task.status, TaskStatus.RUNNING)

    def test_cancel_from_each_non_terminal_state(self):
        for status in TaskStatus:
            if TASK_STATE_MACHINE.is_terminal(status):
                continue

            with self.subTest(status=status):
                task = _make_task(status)

                if status == TaskStatus.READY:
                    task = _make_task(TaskStatus.CREATED)
                    task.ready()
                elif status == TaskStatus.RUNNING:
                    task = _make_task(TaskStatus.CREATED)
                    task.ready()
                    task.start()
                elif status == TaskStatus.PAUSED:
                    task = _make_task(TaskStatus.CREATED)
                    task.ready()
                    task.start()
                    task.pause()
                elif status == TaskStatus.WAITING:
                    task = _make_task(TaskStatus.CREATED)
                    task.schedule()

                task.cancel()
                self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_terminal_states_have_no_exits(self):
        for status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        ):
            task = _make_task(status)

            for method_name in (
                "schedule",
                "ready",
                "start",
                "pause",
                "resume",
                "complete",
                "fail",
                "cancel",
                "skip",
            ):
                with self.subTest(status=status, method=method_name):
                    with self.assertRaises(RuntimeStateTransitionError):
                        getattr(task, method_name)()

                    self.assertEqual(task.status, status)

    def test_invalid_transition_preserves_state_and_fields(self):
        task = _make_task(TaskStatus.CREATED)

        with self.assertRaises(RuntimeStateTransitionError) as ctx:
            task.complete()

        self.assertEqual(task.status, TaskStatus.CREATED)
        self.assertEqual(task.definition_id, "task-1")
        self.assertEqual(ctx.exception.current, TaskStatus.CREATED)
        self.assertEqual(ctx.exception.target, TaskStatus.COMPLETED)
        self.assertEqual(ctx.exception.entity, "Task")

    def test_resume_only_from_paused(self):
        task = _make_task(TaskStatus.READY)

        with self.assertRaises(RuntimeStateTransitionError):
            task.resume()

        self.assertEqual(task.status, TaskStatus.READY)

    def test_complete_fail_pause_only_from_running(self):
        task = _make_task(TaskStatus.READY)

        for method_name in ("complete", "fail", "pause"):
            with self.subTest(method=method_name):
                with self.assertRaises(RuntimeStateTransitionError):
                    getattr(task, method_name)()

                self.assertEqual(task.status, TaskStatus.READY)

    def test_is_terminal(self):
        self.assertFalse(_make_task(TaskStatus.RUNNING).is_terminal)
        self.assertTrue(_make_task(TaskStatus.SKIPPED).is_terminal)

    def test_direct_status_mutation_is_blocked(self):
        task = _make_task()

        with self.assertRaises(AttributeError):
            task.status = TaskStatus.RUNNING

    def test_initial_status_is_created(self):
        self.assertEqual(_make_task().status, TaskStatus.CREATED)
        self.assertEqual(
            _make_workflow_run().status,
            WorkflowStatus.CREATED,
        )


if __name__ == "__main__":
    unittest.main()
