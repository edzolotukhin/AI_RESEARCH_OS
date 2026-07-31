import unittest
from unittest.mock import Mock

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.services.workflow_service import WorkflowService
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
    InMemoryWorkflowTemplateRepository,
)


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
        ],
    )


class WorkflowServiceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.template_repository = InMemoryWorkflowTemplateRepository()
        self.run_repository = InMemoryWorkflowRunRepository()
        self.run_factory = WorkflowRunFactory(task_factory=TaskFactory())
        self.service = WorkflowService(
            workflow_template_repository=self.template_repository,
            workflow_run_repository=self.run_repository,
            workflow_run_factory=self.run_factory,
        )

    def test_create_workflow_run_uses_factory_not_repository_assembly(self) -> None:
        template = _template()
        factory = Mock(spec=WorkflowRunFactory)
        expected_run = self.run_factory.create(template, run_id="run-service-1")
        factory.create.return_value = expected_run

        service = WorkflowService(
            workflow_template_repository=self.template_repository,
            workflow_run_repository=self.run_repository,
            workflow_run_factory=factory,
        )

        result = service.create_workflow_run(
            template,
            project_id="project-1",
            run_id="run-service-1",
        )

        factory.create.assert_called_once_with(
            template=template,
            run_id="run-service-1",
            project_id="project-1",
        )
        self.assertEqual(result.id, "run-service-1")
        self.assertIsNotNone(self.run_repository.get_by_id("run-service-1"))

    def test_create_workflow_run_propagates_duplicate_error(self) -> None:
        template = _template("template-dup")
        self.service.create_workflow_run(
            template,
            project_id="project-1",
            run_id="run-dup",
        )

        with self.assertRaises(DuplicateEntityError):
            self.service.create_workflow_run(
                template,
                project_id="project-1",
                run_id="run-dup",
            )

    def test_get_workflow_run_raises_not_found(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.service.get_workflow_run("missing-run")

    def test_publish_and_list_templates(self) -> None:
        template = _template("template-publish")

        self.service.publish_template_snapshot(
            template,
            project_id="project-1",
        )

        loaded = self.service.get_template("template-publish")
        self.assertEqual(loaded.id, "template-publish")
        self.assertEqual(
            len(self.service.list_templates_for_project("project-1")),
            1,
        )

    def test_save_workflow_run_propagates_concurrency_error(self) -> None:
        workflow_run = self.service.create_workflow_run(
            _template("template-save"),
            project_id="project-1",
            run_id="run-save",
        )

        with self.assertRaises(ConcurrentModificationError):
            self.service.save_workflow_run(workflow_run, expected_version=1)

    def test_get_task_results_round_trip(self) -> None:
        workflow_run = self.service.create_workflow_run(
            _template("template-results"),
            project_id="project-1",
            run_id="run-results",
        )
        task_id = workflow_run.tasks[0].id

        self.service.save_workflow_run(
            workflow_run,
            expected_version=0,
            task_results={task_id: {"summary": "done"}},
        )

        self.assertEqual(
            self.service.get_task_results("run-results"),
            {task_id: {"summary": "done"}},
        )

    def test_list_workflow_runs_for_project(self) -> None:
        self.service.create_workflow_run(
            _template("template-list"),
            project_id="project-list",
            run_id="run-list-1",
        )

        runs = self.service.list_workflow_runs_for_project("project-list")

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].id, "run-list-1")


if __name__ == "__main__":
    unittest.main()
