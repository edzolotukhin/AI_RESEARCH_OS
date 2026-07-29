from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.runtime.state_machine import TASK_STATE_MACHINE
from domain.task import Task
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from application.exceptions.task_scheduling_invariant_error import (
    TaskSchedulingInvariantError,
)
from application.scheduling.scheduling_decision import (
    SchedulingDecisionReason,
    TaskSchedulingDecision,
)
from application.scheduling.scheduling_result import SchedulingResult


_ACTIVE_TASK_STATUSES = frozenset(
    {
        TaskStatus.CREATED,
        TaskStatus.WAITING,
        TaskStatus.READY,
    }
)

_FAILURE_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    }
)

_NON_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.CREATED,
        TaskStatus.WAITING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.PAUSED,
    }
)

_PRE_EXECUTION_STATUSES = frozenset(
    {
        TaskStatus.CREATED,
        TaskStatus.WAITING,
        TaskStatus.READY,
    }
)


class TaskScheduler:
    """
    Canonical dependency-aware scheduler for WorkflowRun tasks.

    Performs one finite scheduling pass over the current WorkflowRun state.
    Uses WorkflowRun.dependency_graph as the runtime dependency model.
    """

    def schedule(
        self,
        workflow_run: WorkflowRun,
    ) -> SchedulingResult:
        task_index = self._build_task_index(workflow_run)
        graph = workflow_run.dependency_graph

        if not workflow_run.tasks:
            self._validate_empty_workflow(workflow_run)
            return SchedulingResult.empty()

        self._validate_workflow_graph(workflow_run)

        evaluated_order = graph.topological_order()
        projected_status = {
            task.id: task.status
            for task in workflow_run.tasks
        }

        decisions: list[TaskSchedulingDecision] = []

        for task_id in evaluated_order:
            task = task_index[task_id]
            dependency_ids = graph.dependencies_of(task_id)

            self._validate_runtime_invariants(
                workflow_run=workflow_run,
                task=task,
                dependency_ids=dependency_ids,
                task_index=task_index,
            )

            decision = self._plan_decision(
                task=task,
                dependency_ids=dependency_ids,
                projected_status=projected_status,
            )
            decisions.append(decision)

            if decision.target_status is not None:
                projected_status[task_id] = decision.target_status

        self._apply_decisions(
            task_index=task_index,
            decisions=decisions,
        )

        return self._build_result(
            decisions=decisions,
            evaluated_order=evaluated_order,
        )

    def resolve_blocked_tasks(
        self,
        workflow_run: WorkflowRun,
    ) -> None:
        self.schedule(workflow_run)

    def validate_dependencies(
        self,
        workflow_run: WorkflowRun,
    ) -> None:
        workflow_run.validate_dependency_graph()

    def get_next_task(
        self,
        workflow_run: WorkflowRun,
    ) -> Task | None:
        self.schedule(workflow_run)
        return self._find_ready_task(workflow_run)

    def find_ready_task(
        self,
        workflow_run: WorkflowRun,
    ) -> Task | None:
        return self._find_ready_task(workflow_run)

    def has_pending_tasks(
        self,
        workflow_run: WorkflowRun,
    ) -> bool:
        return any(
            task.status in _ACTIVE_TASK_STATUSES
            for task in workflow_run.tasks
        )

    def has_waiting_on_incomplete_tasks(
        self,
        workflow_run: WorkflowRun,
    ) -> bool:
        task_index = self._build_task_index(workflow_run)
        graph = workflow_run.dependency_graph

        for task in workflow_run.tasks:
            if task.status not in _ACTIVE_TASK_STATUSES:
                continue

            for dependency_task_id in graph.dependencies_of(task.id):
                dependency = task_index[dependency_task_id]

                if dependency.status in _NON_TERMINAL_STATUSES:
                    return True

        return False

    @staticmethod
    def _build_task_index(
        workflow_run: WorkflowRun,
    ) -> dict[str, Task]:
        task_index: dict[str, Task] = {}
        seen_ids: set[str] = set()

        for task in workflow_run.tasks:
            if task.id in seen_ids:
                raise TaskSchedulingInvariantError(
                    workflow_run_id=workflow_run.id,
                    task_id=task.id,
                    message=(
                        f"WorkflowRun contains duplicate task id '{task.id}'."
                    ),
                )

            seen_ids.add(task.id)
            task_index[task.id] = task

        return task_index

    @staticmethod
    def _validate_empty_workflow(
        workflow_run: WorkflowRun,
    ) -> None:
        if workflow_run.dependency_graph.topological_order():
            raise TaskSchedulingInvariantError(
                workflow_run_id=workflow_run.id,
                task_id="",
                message=(
                    "WorkflowRun has no tasks but dependency graph is not empty."
                ),
            )

    @staticmethod
    def _validate_workflow_graph(
        workflow_run: WorkflowRun,
    ) -> None:
        try:
            workflow_run.validate_dependency_graph()
        except ValidationError as exc:
            raise TaskSchedulingInvariantError(
                workflow_run_id=workflow_run.id,
                task_id="",
                message=str(exc),
            ) from exc

    @staticmethod
    def _validate_runtime_invariants(
        *,
        workflow_run: WorkflowRun,
        task: Task,
        dependency_ids: tuple[str, ...],
        task_index: dict[str, Task],
    ) -> None:
        dependency_statuses = {
            dependency_id: task_index[dependency_id].status
            for dependency_id in dependency_ids
        }

        if task.status == TaskStatus.READY:
            if any(
                status != TaskStatus.COMPLETED
                for status in dependency_statuses.values()
            ):
                TaskScheduler._raise_invariant(
                    workflow_run=workflow_run,
                    task=task,
                    message=(
                        "Task is READY while required dependencies "
                        "are not completed."
                    ),
                    dependency_ids=dependency_ids,
                    dependency_statuses=dependency_statuses,
                )

        if task.status == TaskStatus.RUNNING:
            if any(
                status != TaskStatus.COMPLETED
                for status in dependency_statuses.values()
            ):
                TaskScheduler._raise_invariant(
                    workflow_run=workflow_run,
                    task=task,
                    message=(
                        "Task is RUNNING while required dependencies "
                        "are not completed."
                    ),
                    dependency_ids=dependency_ids,
                    dependency_statuses=dependency_statuses,
                )

        if task.status == TaskStatus.COMPLETED:
            if any(
                status != TaskStatus.COMPLETED
                for status in dependency_statuses.values()
            ):
                TaskScheduler._raise_invariant(
                    workflow_run=workflow_run,
                    task=task,
                    message=(
                        "Task is COMPLETED while a dependency "
                        "was not completed."
                    ),
                    dependency_ids=dependency_ids,
                    dependency_statuses=dependency_statuses,
                )

    @staticmethod
    def _raise_invariant(
        *,
        workflow_run: WorkflowRun,
        task: Task,
        message: str,
        dependency_ids: tuple[str, ...],
        dependency_statuses: dict[str, TaskStatus],
    ) -> None:
        raise TaskSchedulingInvariantError(
            workflow_run_id=workflow_run.id,
            task_id=task.id,
            message=message,
            dependency_ids=dependency_ids,
            dependency_statuses=dependency_statuses,
        )

    @staticmethod
    def _plan_decision(
        *,
        task: Task,
        dependency_ids: tuple[str, ...],
        projected_status: dict[str, TaskStatus],
    ) -> TaskSchedulingDecision:
        current_status = task.status

        if current_status not in _PRE_EXECUTION_STATUSES:
            return TaskSchedulingDecision(
                task_id=task.id,
                current_status=current_status,
                target_status=None,
                reason=SchedulingDecisionReason.NO_CHANGE,
                dependency_ids=dependency_ids,
            )

        if not dependency_ids:
            return TaskScheduler._plan_root_task(
                task=task,
                current_status=current_status,
            )

        dependency_states = [
            projected_status[dependency_id]
            for dependency_id in dependency_ids
        ]

        if any(
            status in _FAILURE_TERMINAL_STATUSES
            for status in dependency_states
        ):
            return TaskScheduler._plan_transition(
                task=task,
                current_status=current_status,
                target_status=TaskStatus.SKIPPED,
                reason=SchedulingDecisionReason.DEPENDENCY_FAILED,
                dependency_ids=dependency_ids,
            )

        if all(
            status == TaskStatus.COMPLETED
            for status in dependency_states
        ):
            return TaskScheduler._plan_transition(
                task=task,
                current_status=current_status,
                target_status=TaskStatus.READY,
                reason=SchedulingDecisionReason.ALL_DEPENDENCIES_COMPLETED,
                dependency_ids=dependency_ids,
            )

        if current_status == TaskStatus.CREATED:
            return TaskScheduler._plan_transition(
                task=task,
                current_status=current_status,
                target_status=TaskStatus.WAITING,
                reason=SchedulingDecisionReason.WAITING_FOR_DEPENDENCIES,
                dependency_ids=dependency_ids,
            )

        return TaskSchedulingDecision(
            task_id=task.id,
            current_status=current_status,
            target_status=None,
            reason=SchedulingDecisionReason.NO_CHANGE,
            dependency_ids=dependency_ids,
        )

    @staticmethod
    def _plan_root_task(
        *,
        task: Task,
        current_status: TaskStatus,
    ) -> TaskSchedulingDecision:
        if current_status in {
            TaskStatus.CREATED,
            TaskStatus.WAITING,
        }:
            return TaskScheduler._plan_transition(
                task=task,
                current_status=current_status,
                target_status=TaskStatus.READY,
                reason=SchedulingDecisionReason.ROOT_TASK,
                dependency_ids=(),
            )

        return TaskSchedulingDecision(
            task_id=task.id,
            current_status=current_status,
            target_status=None,
            reason=SchedulingDecisionReason.NO_CHANGE,
            dependency_ids=(),
        )

    @staticmethod
    def _plan_transition(
        *,
        task: Task,
        current_status: TaskStatus,
        target_status: TaskStatus,
        reason: SchedulingDecisionReason,
        dependency_ids: tuple[str, ...],
    ) -> TaskSchedulingDecision:
        if current_status == target_status:
            return TaskSchedulingDecision(
                task_id=task.id,
                current_status=current_status,
                target_status=None,
                reason=SchedulingDecisionReason.NO_CHANGE,
                dependency_ids=dependency_ids,
            )

        if not TASK_STATE_MACHINE.can_transition(
            current_status,
            target_status,
        ):
            raise TaskSchedulingInvariantError(
                workflow_run_id="",
                task_id=task.id,
                message=(
                    f"Planned transition from {current_status.value} "
                    f"to {target_status.value} is not allowed."
                ),
                dependency_ids=dependency_ids,
            )

        return TaskSchedulingDecision(
            task_id=task.id,
            current_status=current_status,
            target_status=target_status,
            reason=reason,
            dependency_ids=dependency_ids,
        )

    @staticmethod
    def _apply_decisions(
        *,
        task_index: dict[str, Task],
        decisions: list[TaskSchedulingDecision],
    ) -> None:
        for decision in decisions:
            if decision.target_status is None:
                continue

            task = task_index[decision.task_id]

            if decision.target_status == TaskStatus.WAITING:
                task.schedule()
                continue

            if decision.target_status == TaskStatus.READY:
                task.ready()
                continue

            if decision.target_status == TaskStatus.SKIPPED:
                task.skip()

    @staticmethod
    def _build_result(
        *,
        decisions: list[TaskSchedulingDecision],
        evaluated_order: tuple[str, ...],
    ) -> SchedulingResult:
        ready_task_ids: list[str] = []
        waiting_task_ids: list[str] = []
        skipped_task_ids: list[str] = []
        unchanged_task_ids: list[str] = []
        transition_count = 0
        has_dependency_failures = False

        for decision in decisions:
            if decision.target_status is None:
                unchanged_task_ids.append(decision.task_id)
                continue

            transition_count += 1

            if decision.reason == SchedulingDecisionReason.DEPENDENCY_FAILED:
                has_dependency_failures = True

            if decision.target_status == TaskStatus.READY:
                ready_task_ids.append(decision.task_id)
            elif decision.target_status == TaskStatus.WAITING:
                waiting_task_ids.append(decision.task_id)
            elif decision.target_status == TaskStatus.SKIPPED:
                skipped_task_ids.append(decision.task_id)

        return SchedulingResult(
            ready_task_ids=tuple(ready_task_ids),
            waiting_task_ids=tuple(waiting_task_ids),
            skipped_task_ids=tuple(skipped_task_ids),
            unchanged_task_ids=tuple(unchanged_task_ids),
            evaluated_task_ids=evaluated_order,
            transition_count=transition_count,
            has_changes=transition_count > 0,
            has_dependency_failures=has_dependency_failures,
        )

    @staticmethod
    def _find_ready_task(
        workflow_run: WorkflowRun,
    ) -> Task | None:
        task_index = {
            task.id: task
            for task in workflow_run.tasks
        }

        for task_id in workflow_run.dependency_graph.topological_order():
            task = task_index[task_id]

            if task.status == TaskStatus.READY:
                return task

        return None
