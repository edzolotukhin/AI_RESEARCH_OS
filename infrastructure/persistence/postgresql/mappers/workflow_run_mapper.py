from __future__ import annotations

from typing import Any

from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.task import Task
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.postgresql.models.task_model import WorkflowTaskModel
from infrastructure.persistence.postgresql.models.workflow_run_model import (
    WorkflowRunModel,
)


def workflow_run_to_model(
    workflow_run: WorkflowRun,
    *,
    project_id: str,
    version: int,
    task_results: dict[str, Any] | None = None,
) -> WorkflowRunModel:
    model = WorkflowRunModel(
        id=workflow_run.id,
        project_id=project_id or workflow_run.project_id,
        workflow_template_id=workflow_run.workflow_template_id,
        status=workflow_run.status.value,
        dependency_graph=dependency_graph_to_dict(workflow_run.dependency_graph),
        task_results=task_results if task_results is not None else {},
        version=version,
    )
    model.tasks = [
        _task_to_model(task, workflow_run_id=workflow_run.id, sort_order=index)
        for index, task in enumerate(workflow_run.tasks)
    ]
    return model


def workflow_run_to_update_values(
    workflow_run: WorkflowRun,
    *,
    task_results: dict[str, Any] | None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workflow_template_id": workflow_run.workflow_template_id,
        "status": workflow_run.status.value,
        "dependency_graph": dependency_graph_to_dict(
            workflow_run.dependency_graph,
        ),
    }
    if workflow_run.project_id:
        values["project_id"] = workflow_run.project_id
    if task_results is not None:
        values["task_results"] = task_results
    return values


def workflow_run_from_model(model: WorkflowRunModel) -> WorkflowRun:
    tasks = [_task_from_model(task_model) for task_model in model.tasks]
    dependency_graph = dependency_graph_from_dict(model.dependency_graph)
    if not model.dependency_graph:
        dependency_graph = _rebuild_graph_from_tasks(tasks)

    return WorkflowRun(
        id=model.id,
        project_id=model.project_id,
        workflow_template_id=model.workflow_template_id,
        tasks=tasks,
        dependency_graph=dependency_graph,
        status=WorkflowStatus(model.status),
    )


def dependency_graph_to_dict(graph: TaskDependencyGraph) -> dict[str, Any]:
    nodes = list(graph.topological_order())
    if not nodes:
        return {"nodes": [], "edges": []}

    edges: list[list[str]] = []
    for node in nodes:
        for dependency in graph.dependencies_of(node):
            edges.append([dependency, node])

    return {"nodes": nodes, "edges": edges}


def dependency_graph_from_dict(payload: dict[str, Any]) -> TaskDependencyGraph:
    graph = TaskDependencyGraph()
    nodes = list(payload.get("nodes", []))
    for node in nodes:
        graph.add_task(node)
    for edge in payload.get("edges", []):
        if len(edge) == 2:
            graph.add_dependency(edge[0], edge[1])
    return graph


def _rebuild_graph_from_tasks(tasks: list[Task]) -> TaskDependencyGraph:
    graph = TaskDependencyGraph()
    for task in tasks:
        graph.add_task(task.id)
    for task in tasks:
        for dependency in task.depends_on:
            graph.add_dependency(dependency, task.id)
    return graph


def _task_to_model(
    task: Task,
    *,
    workflow_run_id: str,
    sort_order: int,
) -> WorkflowTaskModel:
    return WorkflowTaskModel(
        workflow_run_id=workflow_run_id,
        task_id=task.id,
        definition_id=task.definition_id,
        name=task.name,
        description=task.description,
        executor_id=task.executor_id,
        executor_type=task.executor_type.value,
        depends_on=list(task.depends_on),
        status=task.status.value,
        created_at=task.created_at,
        updated_at=task.updated_at,
        sort_order=sort_order,
    )


def _task_from_model(model: WorkflowTaskModel) -> Task:
    return Task(
        id=model.task_id,
        definition_id=model.definition_id,
        name=model.name,
        description=model.description,
        executor_id=model.executor_id,
        executor_type=ExecutorType(model.executor_type),
        depends_on=list(model.depends_on or []),
        status=TaskStatus(model.status),
        created_at=model.created_at or "",
        updated_at=model.updated_at or "",
    )
