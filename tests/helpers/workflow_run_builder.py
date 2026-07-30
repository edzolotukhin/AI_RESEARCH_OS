from uuid import uuid4

from domain.factories.workflow_run_dependency_graph_builder import (
    WorkflowRunDependencyGraphBuilder,
)
from domain.task import Task
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun


def make_task(
    definition_id: str,
    *,
    depends_on: list[str] | None = None,
    status: TaskStatus = TaskStatus.CREATED,
    executor_id: str = "test",
    executor_type: ExecutorType = ExecutorType.AGENT,
    task_id: str | None = None,
) -> Task:
    return Task(
        id=task_id or str(uuid4()),
        definition_id=definition_id,
        name=definition_id,
        executor_id=executor_id,
        executor_type=executor_type,
        depends_on=list(depends_on or []),
        status=status,
    )


def make_workflow_run(
    *tasks: Task,
    run_id: str = "run-1",
    template_id: str = "template-1",
) -> WorkflowRun:
    task_list = list(tasks)
    dependency_graph = WorkflowRunDependencyGraphBuilder.build_from_tasks(
        task_list,
        workflow_template_id=template_id,
    )

    workflow_run = WorkflowRun(
        id=run_id,
        workflow_template_id=template_id,
        tasks=task_list,
        dependency_graph=dependency_graph,
    )
    workflow_run.validate_dependency_graph()

    return workflow_run
