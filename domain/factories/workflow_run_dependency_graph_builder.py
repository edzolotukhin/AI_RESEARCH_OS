from __future__ import annotations

from domain.exceptions.task_dependency_graph_error import (
    TaskDependencyCycleError,
    TaskSelfDependencyError,
)
from domain.exceptions.workflow_run_factory_error import (
    DuplicateTaskDefinitionIdError,
    UnknownTaskDefinitionDependencyError,
    WorkflowRunDependencyGraphBuildError,
)
from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.task import Task
from domain.workflow_template import WorkflowTemplate


class WorkflowRunDependencyGraphBuilder:
    """
    Builds a runtime TaskDependencyGraph for a WorkflowRun.
    """

    @classmethod
    def build_from_template(
        cls,
        template: WorkflowTemplate,
        tasks: list[Task],
    ) -> TaskDependencyGraph:
        cls._ensure_unique_definition_ids(template)
        definition_to_task_id = cls._build_definition_mapping(
            template,
            tasks,
        )

        graph = TaskDependencyGraph()

        for task in tasks:
            graph.add_task(task.id)

        for definition in template.task_definitions:
            dependent_task_id = definition_to_task_id[definition.id]

            for dependency_definition_id in definition.depends_on:
                if dependency_definition_id not in definition_to_task_id:
                    raise UnknownTaskDefinitionDependencyError(
                        workflow_template_id=template.id,
                        task_definition_id=definition.id,
                        dependency_definition_id=dependency_definition_id,
                    )

                dependency_task_id = definition_to_task_id[
                    dependency_definition_id
                ]

                cls._add_dependency(
                    graph=graph,
                    template=template,
                    task_definition_id=definition.id,
                    dependency_task_id=dependency_task_id,
                    dependent_task_id=dependent_task_id,
                )

        graph.validate()
        return graph

    @classmethod
    def build_from_tasks(
        cls,
        tasks: list[Task],
        *,
        workflow_template_id: str = "",
    ) -> TaskDependencyGraph:
        definition_to_task_id = {
            task.definition_id: task.id
            for task in tasks
        }

        if len(definition_to_task_id) != len(tasks):
            duplicate = cls._find_duplicate_definition_id(tasks)
            raise DuplicateTaskDefinitionIdError(
                workflow_template_id=workflow_template_id,
                definition_id=duplicate,
            )

        graph = TaskDependencyGraph()

        for task in tasks:
            graph.add_task(task.id)

        for task in tasks:
            for dependency_definition_id in task.depends_on:
                if dependency_definition_id not in definition_to_task_id:
                    raise UnknownTaskDefinitionDependencyError(
                        workflow_template_id=workflow_template_id,
                        task_definition_id=task.definition_id,
                        dependency_definition_id=dependency_definition_id,
                    )

                cls._add_dependency(
                    graph=graph,
                    template_id=workflow_template_id,
                    task_definition_id=task.definition_id,
                    dependency_task_id=definition_to_task_id[
                        dependency_definition_id
                    ],
                    dependent_task_id=task.id,
                )

        if tasks:
            graph.validate()

        return graph

    @staticmethod
    def _ensure_unique_definition_ids(
        template: WorkflowTemplate,
    ) -> None:
        seen: set[str] = set()

        for definition in template.task_definitions:
            if definition.id in seen:
                raise DuplicateTaskDefinitionIdError(
                    workflow_template_id=template.id,
                    definition_id=definition.id,
                )

            seen.add(definition.id)

    @staticmethod
    def _build_definition_mapping(
        template: WorkflowTemplate,
        tasks: list[Task],
    ) -> dict[str, str]:
        definition_to_task_id: dict[str, str] = {}

        for task in tasks:
            if task.definition_id in definition_to_task_id:
                raise DuplicateTaskDefinitionIdError(
                    workflow_template_id=template.id,
                    definition_id=task.definition_id,
                )

            definition_to_task_id[task.definition_id] = task.id

        expected_definition_ids = {
            definition.id
            for definition in template.task_definitions
        }

        if set(definition_to_task_id) != expected_definition_ids:
            missing = expected_definition_ids - set(definition_to_task_id)
            extra = set(definition_to_task_id) - expected_definition_ids

            if missing:
                raise WorkflowRunDependencyGraphBuildError(
                    workflow_template_id=template.id,
                    task_definition_id=next(iter(missing)),
                    message=(
                        "Runtime task mapping is missing task definitions: "
                        f"{sorted(missing)}."
                    ),
                )

            raise WorkflowRunDependencyGraphBuildError(
                workflow_template_id=template.id,
                task_definition_id=next(iter(extra)),
                message=(
                    "Runtime task mapping contains unexpected task definitions: "
                    f"{sorted(extra)}."
                ),
            )

        return definition_to_task_id

    @staticmethod
    def _find_duplicate_definition_id(
        tasks: list[Task],
    ) -> str:
        seen: set[str] = set()

        for task in tasks:
            if task.definition_id in seen:
                return task.definition_id

            seen.add(task.definition_id)

        return ""

    @classmethod
    def _add_dependency(
        cls,
        *,
        graph: TaskDependencyGraph,
        dependency_task_id: str,
        dependent_task_id: str,
        task_definition_id: str,
        template: WorkflowTemplate | None = None,
        template_id: str = "",
    ) -> None:
        workflow_template_id = (
            template.id if template is not None else template_id
        )

        try:
            graph.add_dependency(
                dependency_task_id,
                dependent_task_id,
            )
        except TaskSelfDependencyError as exc:
            raise WorkflowRunDependencyGraphBuildError(
                workflow_template_id=workflow_template_id,
                task_definition_id=task_definition_id,
                message=str(exc),
            ) from exc
        except TaskDependencyCycleError as exc:
            raise WorkflowRunDependencyGraphBuildError(
                workflow_template_id=workflow_template_id,
                task_definition_id=task_definition_id,
                message=str(exc),
            ) from exc
