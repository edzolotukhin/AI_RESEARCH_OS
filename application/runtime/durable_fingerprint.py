from __future__ import annotations

import json
from typing import Any

from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext


def canonical_dependency_graph(graph: TaskDependencyGraph) -> dict[str, Any]:
    """Stable JSON-serializable representation of a dependency graph."""
    nodes = list(graph.topological_order())
    if not nodes:
        return {"nodes": [], "edges": []}

    edges: list[list[str]] = []
    for node in nodes:
        for dependency in graph.dependencies_of(node):
            edges.append([dependency, node])

    return {"nodes": nodes, "edges": edges}


def durable_recovery_fingerprint(
    context: WorkflowContext,
    task_results: dict[str, Any],
) -> str:
    """
    Deterministic fingerprint of all durable recovery state.

    Uses canonical JSON (sorted keys, Unicode preserved) and excludes
    persistence version, execution logs, and transient WorkflowContext fields.
    """
    workflow_run = context.workflow_run
    task_by_id = {task.id: task for task in workflow_run.tasks}

    tasks_payload: list[dict[str, str]] = []
    for task_id in workflow_run.dependency_graph.topological_order():
        task = task_by_id[task_id]
        tasks_payload.append(
            {
                "id": task.id,
                "status": task.status.value,
            }
        )

    payload = {
        "dependency_graph": canonical_dependency_graph(workflow_run.dependency_graph),
        "task_results": task_results,
        "tasks": tasks_payload,
        "workflow_status": workflow_run.status.value,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)
