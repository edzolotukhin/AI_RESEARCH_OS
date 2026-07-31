"""
Repository contract tests for WorkflowTemplate, Artifact, and Knowledge ports.

These are port contract tests — shared semantics every compliant adapter must
satisfy. Adapter-specific behavior belongs in tests/infrastructure/persistence/.
"""
from __future__ import annotations

import unittest
from abc import abstractmethod

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import ArtifactRecord, KnowledgeItem
from application.ports.artifact_repository import ArtifactRepository
from application.ports.knowledge_repository import KnowledgeRepository
from application.ports.workflow_template_repository import (
    WorkflowTemplateRepository,
)
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate


class WorkflowTemplateRepositoryContractTests:
    repository: WorkflowTemplateRepository

    @abstractmethod
    def build_repository(self) -> WorkflowTemplateRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.repository = self.build_repository()

    def test_save_snapshot_and_get_by_id(self) -> None:
        template = WorkflowTemplate(
            id="template-1",
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

        self.repository.save_snapshot(template, project_id="project-1")
        loaded = self.repository.get_by_id("template-1")

        assert loaded is not None
        self.assertEqual(loaded.id, "template-1")
        self.assertEqual(len(loaded.task_definitions), 1)

    def test_list_for_project(self) -> None:
        first = WorkflowTemplate(id="template-a", name="A")
        second = WorkflowTemplate(id="template-b", name="B")

        self.repository.save_snapshot(first, project_id="project-1")
        self.repository.save_snapshot(second, project_id="project-1")

        templates = self.repository.list_for_project("project-1")

        self.assertEqual(
            {template.id for template in templates},
            {"template-a", "template-b"},
        )


class InMemoryWorkflowTemplateRepositoryContractTests(
    WorkflowTemplateRepositoryContractTests,
    unittest.TestCase,
):
    def build_repository(self) -> WorkflowTemplateRepository:
        from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
            InMemoryWorkflowTemplateRepository,
        )

        return InMemoryWorkflowTemplateRepository()


class ArtifactRepositoryContractTests:
    repository: ArtifactRepository

    @abstractmethod
    def build_repository(self) -> ArtifactRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.repository = self.build_repository()

    def test_save_and_get_by_id(self) -> None:
        artifact = ArtifactRecord(
            id="artifact-1",
            project_id="project-1",
            run_id="run-1",
            artifact_type="report",
            title="Report",
            content="Body",
        )

        version = self.repository.save(artifact)
        loaded = self.repository.get_by_id("artifact-1")

        assert loaded is not None
        self.assertEqual(loaded.title, "Report")
        self.assertEqual(version, 1)

    def test_list_for_project_and_run(self) -> None:
        artifact = ArtifactRecord(
            id="artifact-2",
            project_id="project-1",
            run_id="run-1",
            artifact_type="report",
            title="Report",
            content="Body",
        )

        self.repository.save(artifact)

        self.assertEqual(len(self.repository.list_for_project("project-1")), 1)
        self.assertEqual(len(self.repository.list_for_run("run-1")), 1)


class InMemoryArtifactRepositoryContractTests(
    ArtifactRepositoryContractTests,
    unittest.TestCase,
):
    def build_repository(self) -> ArtifactRepository:
        from infrastructure.persistence.memory.in_memory_artifact_repository import (
            InMemoryArtifactRepository,
        )

        return InMemoryArtifactRepository()


class KnowledgeRepositoryContractTests:
    repository: KnowledgeRepository

    @abstractmethod
    def build_repository(self) -> KnowledgeRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.repository = self.build_repository()

    def test_save_get_list_and_delete(self) -> None:
        item = KnowledgeItem(
            id="knowledge-1",
            project_id="project-1",
            title="Brief",
            content="Content",
        )

        version = self.repository.save(item)
        loaded = self.repository.get_by_id("knowledge-1")

        assert loaded is not None
        self.assertEqual(version, 1)
        self.assertEqual(len(self.repository.list_for_project("project-1")), 1)

        self.repository.delete("knowledge-1")

        self.assertIsNone(self.repository.get_by_id("knowledge-1"))

    def test_save_with_stale_expected_version_raises(self) -> None:
        item = KnowledgeItem(
            id="knowledge-2",
            project_id="project-1",
            title="Brief",
            content="Content",
        )

        self.repository.save(item)

        with self.assertRaises(ConcurrentModificationError):
            self.repository.save(item, expected_version=0)


class InMemoryKnowledgeRepositoryContractTests(
    KnowledgeRepositoryContractTests,
    unittest.TestCase,
):
    def build_repository(self) -> KnowledgeRepository:
        from infrastructure.persistence.memory.in_memory_knowledge_repository import (
            InMemoryKnowledgeRepository,
        )

        return InMemoryKnowledgeRepository()


if __name__ == "__main__":
    unittest.main()
