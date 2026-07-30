from __future__ import annotations

from domain.common.exceptions import ValidationError
from domain.exceptions.task_dependency_graph_error import (
    TaskDependencyCycleError,
    TaskNotFoundInDependencyGraphError,
    TaskSelfDependencyError,
)


class TaskDependencyGraph:
    """
    Directed acyclic graph of task dependencies for a single WorkflowRun.

    Nodes are task identifiers. An edge dependency -> dependent means the
    dependent task requires the dependency task to finish first.
    """

    def __init__(self) -> None:
        self._nodes: list[str] = []
        self._node_set: set[str] = set()
        self._dependencies: dict[str, set[str]] = {}
        self._dependents: dict[str, set[str]] = {}
        self._edges: set[tuple[str, str]] = set()

    def add_task(
        self,
        task_id: str,
    ) -> None:
        if task_id in self._node_set:
            return

        self._nodes.append(task_id)
        self._node_set.add(task_id)
        self._dependencies.setdefault(task_id, set())
        self._dependents.setdefault(task_id, set())

    def add_dependency(
        self,
        dependency_task_id: str,
        dependent_task_id: str,
    ) -> None:
        self._ensure_task_exists(dependency_task_id)
        self._ensure_task_exists(dependent_task_id)

        if dependency_task_id == dependent_task_id:
            raise TaskSelfDependencyError(dependent_task_id)

        edge = (dependency_task_id, dependent_task_id)

        if edge in self._edges:
            return

        cycle_path = self._find_cycle_path(
            dependency_task_id,
            dependent_task_id,
        )

        if cycle_path is not None:
            raise TaskDependencyCycleError(
                dependency_task_id,
                dependent_task_id,
                cycle_path,
            )

        self._edges.add(edge)
        self._dependencies[dependent_task_id].add(dependency_task_id)
        self._dependents[dependency_task_id].add(dependent_task_id)

    def has_task(
        self,
        task_id: str,
    ) -> bool:
        return task_id in self._node_set

    def has_dependency(
        self,
        dependency_task_id: str,
        dependent_task_id: str,
    ) -> bool:
        return (
            dependency_task_id,
            dependent_task_id,
        ) in self._edges

    def dependencies_of(
        self,
        task_id: str,
    ) -> tuple[str, ...]:
        self._ensure_task_exists(task_id)

        return self._sorted_neighbors(
            self._dependencies[task_id],
        )

    def dependents_of(
        self,
        task_id: str,
    ) -> tuple[str, ...]:
        self._ensure_task_exists(task_id)

        return self._sorted_neighbors(
            self._dependents[task_id],
        )

    def root_tasks(self) -> tuple[str, ...]:
        roots = [
            task_id
            for task_id in self._nodes
            if not self._dependencies[task_id]
        ]

        return tuple(roots)

    def leaf_tasks(self) -> tuple[str, ...]:
        leaves = [
            task_id
            for task_id in self._nodes
            if not self._dependents[task_id]
        ]

        return tuple(leaves)

    def topological_order(self) -> tuple[str, ...]:
        if not self._nodes:
            return ()

        in_degree = {
            task_id: len(self._dependencies[task_id])
            for task_id in self._nodes
        }

        ready = [
            task_id
            for task_id in self._nodes
            if in_degree[task_id] == 0
        ]

        ordered: list[str] = []

        while ready:
            current = ready.pop(0)
            ordered.append(current)

            for dependent in self._sorted_neighbors(
                self._dependents[current],
            ):
                in_degree[dependent] -= 1

                if in_degree[dependent] == 0:
                    ready.append(dependent)

            ready.sort(key=self._nodes.index)

        if len(ordered) != len(self._nodes):
            raise ValidationError(
                "Task dependency graph contains a cycle."
            )

        return tuple(ordered)

    def validate(self) -> None:
        if len(self._node_set) != len(self._nodes):
            raise ValidationError(
                "Task dependency graph contains duplicate nodes."
            )

        for task_id in self._nodes:
            if task_id not in self._node_set:
                raise ValidationError(
                    f"Unknown node '{task_id}' in insertion order."
                )

        for dependency_task_id, dependent_task_id in self._edges:
            if dependency_task_id not in self._node_set:
                raise ValidationError(
                    "Dependency references unknown task "
                    f"'{dependency_task_id}'."
                )

            if dependent_task_id not in self._node_set:
                raise ValidationError(
                    "Dependency references unknown task "
                    f"'{dependent_task_id}'."
                )

            if dependency_task_id == dependent_task_id:
                raise ValidationError(
                    f"Task '{dependency_task_id}' has a self-dependency."
                )

            if dependency_task_id not in self._dependencies[dependent_task_id]:
                raise ValidationError(
                    "Forward and reverse dependency indexes are inconsistent."
                )

            if dependent_task_id not in self._dependents[dependency_task_id]:
                raise ValidationError(
                    "Forward and reverse dependency indexes are inconsistent."
                )

        ordered = self.topological_order()

        if len(ordered) != len(self._nodes):
            raise ValidationError(
                "Topological order does not contain every node exactly once."
            )

        positions = {
            task_id: index
            for index, task_id in enumerate(ordered)
        }

        for dependency_task_id, dependent_task_id in self._edges:
            if positions[dependency_task_id] >= positions[dependent_task_id]:
                raise ValidationError(
                    "Topological order violates dependency ordering."
                )

    def _ensure_task_exists(
        self,
        task_id: str,
    ) -> None:
        if task_id not in self._node_set:
            raise TaskNotFoundInDependencyGraphError(task_id)

    def _sorted_neighbors(
        self,
        neighbors: set[str],
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                neighbors,
                key=self._nodes.index,
            )
        )

    def _find_cycle_path(
        self,
        dependency_task_id: str,
        dependent_task_id: str,
    ) -> tuple[str, ...] | None:
        stack: list[tuple[str, tuple[str, ...]]] = [
            (dependency_task_id, (dependency_task_id,)),
        ]

        while stack:
            node, path = stack.pop()

            for prerequisite in self._sorted_neighbors(
                self._dependencies[node],
            ):
                if prerequisite == dependent_task_id:
                    return path + (dependent_task_id,)

                if prerequisite in path:
                    continue

                stack.append(
                    (prerequisite, path + (prerequisite,)),
                )

        return None
