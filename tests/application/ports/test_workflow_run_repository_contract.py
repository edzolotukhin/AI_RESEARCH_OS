from __future__ import annotations

import unittest
from abc import abstractmethod

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.workflow_run_repository import WorkflowRunRepository
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_template import WorkflowTemplate


def _template(template_id: str = "template-1") -> WorkflowTemplate:
    return WorkflowTemplate(
        id=template_id,
        name="Template",
        task_definitions=[
            TaskDefinition(
                id="task-a",
                name="Task A",
                executor_id="planner",
                executor_type=ExecutorType.AGENT,
            ),
            TaskDefinition(
                id="task-b",
                name="Task B",
                executor_id="search",
                executor_type=ExecutorType.AGENT,
                depends_on=["task-a"],
            ),
        ],
    )


class WorkflowRunRepositoryContractTests:
    """
    Shared behavioral contract for WorkflowRunRepository port implementations.

    Aggregate assembly is performed by WorkflowRunFactory in test setup —
    the repository under test only persists pre-constructed aggregates.
    """

    repository: WorkflowRunRepository
    workflow_run_factory: WorkflowRunFactory

    @abstractmethod
    def build_repository(self) -> WorkflowRunRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.repository = self.build_repository()
        self.workflow_run_factory = WorkflowRunFactory(
            task_factory=TaskFactory(),
        )

    def test_create_persists_prebuilt_aggregate(self) -> None:
        workflow_run = self.workflow_run_factory.create(
            _template(),
            run_id="run-contract-1",
        )

        self.repository.create(workflow_run, project_id="project-1")

        loaded = self.repository.get_by_id("run-contract-1")
        assert loaded is not None
        self.assertEqual(len(loaded.tasks), 2)
        loaded.validate_dependency_graph()

    def test_create_rejects_duplicate_id(self) -> None:
        workflow_run = self.workflow_run_factory.create(
            _template("template-dup"),
            run_id="run-dup",
        )

        self.repository.create(workflow_run, project_id="project-1")

        with self.assertRaises(DuplicateEntityError):
            self.repository.create(workflow_run, project_id="project-1")

    def test_save_rejects_missing_aggregate(self) -> None:
        workflow_run = self.workflow_run_factory.create(
            _template("template-missing"),
            run_id="run-missing",
        )

        with self.assertRaises(EntityNotFoundError):
            self.repository.save(workflow_run)

    def test_save_and_task_results_round_trip(self) -> None:
        workflow_run = self.workflow_run_factory.create(
            _template("template-results"),
            run_id="run-results",
        )
        self.repository.create(workflow_run, project_id="project-1")

        task_id = workflow_run.tasks[0].id
        workflow_run.tasks[0].ready()
        workflow_run.tasks[0].start()
        workflow_run.tasks[0].complete()

        version = self.repository.save(
            workflow_run,
            expected_version=1,
            task_results={task_id: {"summary": "done"}},
        )

        loaded = self.repository.get_by_id("run-results")
        assert loaded is not None
        self.assertEqual(loaded.tasks[0].status, TaskStatus.COMPLETED)
        self.assertEqual(version, 2)
        self.assertEqual(
            self.repository.get_task_results("run-results"),
            {task_id: {"summary": "done"}},
        )

    def test_save_with_stale_expected_version_raises(self) -> None:
        workflow_run = self.workflow_run_factory.create(
            _template("template-version"),
            run_id="run-version",
        )
        self.repository.create(workflow_run, project_id="project-1")

        with self.assertRaises(ConcurrentModificationError):
            self.repository.save(workflow_run, expected_version=0)

    def test_list_for_project_filters_by_status(self) -> None:
        first = self.workflow_run_factory.create(
            _template("template-list-1"),
            run_id="run-list-1",
        )
        second = self.workflow_run_factory.create(
            _template("template-list-2"),
            run_id="run-list-2",
        )

        self.repository.create(first, project_id="project-list")
        self.repository.create(second, project_id="project-list")

        second.ready()
        self.repository.save(second, expected_version=1)

        all_runs = self.repository.list_for_project("project-list")
        ready_runs = self.repository.list_for_project(
            "project-list",
            status=first.status,
        )

        self.assertEqual(len(all_runs), 2)
        self.assertEqual(len(ready_runs), 1)


class InMemoryWorkflowRunRepositoryContractTests(
    WorkflowRunRepositoryContractTests,
    unittest.TestCase,
):
    def build_repository(self) -> WorkflowRunRepository:
        from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
            InMemoryWorkflowRunRepository,
        )

        return InMemoryWorkflowRunRepository()


if __name__ == "__main__":
    unittest.main()
