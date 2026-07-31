from __future__ import annotations

import json
from typing import Any

from domain.value_objects.task_status import TaskStatus
from runtime.workflow_context import WorkflowContext


class NonSerializableTaskResultError(TypeError):
    """Raised when a task result cannot be persisted as JSON."""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    raise NonSerializableTaskResultError(
        f"Task result contains non-JSON-serializable value: {type(value)!r}"
    )


def capture_task_result(
    context: WorkflowContext,
    task_id: str,
) -> dict[str, Any]:
    """Build a JSON-serializable durable snapshot for one completed task."""
    task = context.current_task
    definition_id = task.definition_id if task is not None else None

    snapshot = {
        "task_id": task_id,
        "definition_id": definition_id,
        "shared_state": _json_safe(dict(context.shared_state)),
    }
    json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return snapshot


def restore_runtime_state(
    context: WorkflowContext,
    task_results: dict[str, Any],
) -> None:
    """
    Rehydrate transient runtime state from durable task result snapshots.

    Snapshots are applied in dependency-graph topological order. Only COMPLETED
    tasks with persisted task_results participate. When snapshots contain the
    same shared_state key, the later snapshot in topological order wins.
    Independent-task ordering follows TaskDependencyGraph deterministic
    tie-break (insertion order within each ready frontier).
    """
    workflow_run = context.workflow_run
    task_by_id = {task.id: task for task in workflow_run.tasks}
    merged_shared_state: dict[str, Any] = {}
    intermediate_results: dict[str, Any] = {}

    for task_id in workflow_run.dependency_graph.topological_order():
        task = task_by_id.get(task_id)
        if task is None or task.status != TaskStatus.COMPLETED:
            continue

        snapshot = task_results.get(task_id)
        if not isinstance(snapshot, dict):
            continue

        intermediate_results[task_id] = snapshot
        shared_state = snapshot.get("shared_state")
        if isinstance(shared_state, dict):
            merged_shared_state.update(shared_state)

    context.shared_state.update(merged_shared_state)
    context.intermediate_results.update(intermediate_results)
