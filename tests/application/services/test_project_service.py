import unittest
from unittest.mock import Mock

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.services.project_service import ProjectService
from domain.factories.project_factory import ProjectFactory
from domain.project import Project

from infrastructure.persistence.memory.in_memory_project_repository import (
    InMemoryProjectRepository,
)


class ProjectServiceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.repository = InMemoryProjectRepository()
        self.service = ProjectService(
            project_factory=ProjectFactory(),
            project_repository=self.repository,
        )

    def test_create_project_uses_factory_and_persists(self) -> None:
        project = self.service.create_project("Research Project")

        self.assertIsInstance(project, Project)
        self.assertEqual(project.name, "Research Project")

        loaded = self.service.get_project(project.id)
        self.assertEqual(loaded.id, project.id)

    def test_create_project_rejects_duplicate_id(self) -> None:
        factory = Mock(spec=ProjectFactory)
        project = Project(id="dup-id", name="Dup", created_at="", updated_at="")
        factory.create.return_value = project
        service = ProjectService(
            project_factory=factory,
            project_repository=InMemoryProjectRepository(),
        )

        service.create_project("First")

        with self.assertRaises(DuplicateEntityError):
            service.create_project("Second")

    def test_get_project_raises_not_found(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.service.get_project("missing-id")

    def test_list_projects_returns_persisted_projects(self) -> None:
        first = self.service.create_project("First")
        second = self.service.create_project("Second")

        projects = self.service.list_projects()

        self.assertEqual(
            {project.id for project in projects},
            {first.id, second.id},
        )

    def test_save_project_with_optimistic_concurrency(self) -> None:
        project = self.service.create_project("Versioned")
        first_version = self.service.save_project(project, expected_version=0)
        second_version = self.service.save_project(
            project,
            expected_version=first_version,
        )

        self.assertEqual(first_version, 1)
        self.assertEqual(second_version, 2)

    def test_save_project_rejects_stale_version(self) -> None:
        project = self.service.create_project("Stale")

        self.service.save_project(project, expected_version=0)

        with self.assertRaises(ConcurrentModificationError):
            self.service.save_project(project, expected_version=0)

    def test_delete_project_removes_aggregate(self) -> None:
        project = self.service.create_project("Delete Me")

        self.service.delete_project(project.id)

        with self.assertRaises(EntityNotFoundError):
            self.service.get_project(project.id)

    def test_delete_project_raises_not_found(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.service.delete_project("missing-id")

    def test_delete_project_with_expected_version(self) -> None:
        project = self.service.create_project("Delete Versioned")

        self.service.delete_project(project.id, expected_version=0)

        with self.assertRaises(EntityNotFoundError):
            self.service.get_project(project.id)

    def test_delete_project_rejects_stale_expected_version(self) -> None:
        project = self.service.create_project("Stale Delete")
        self.service.save_project(project, expected_version=0)

        with self.assertRaises(ConcurrentModificationError):
            self.service.delete_project(project.id, expected_version=0)


class ProjectServiceMockedRepositoryTests(unittest.TestCase):

    def test_create_project_invokes_create_once_without_save(self) -> None:
        project = Project(id="project-1", name="Test")
        factory = Mock(spec=ProjectFactory)
        factory.create.return_value = project
        repository = Mock()
        service = ProjectService(
            project_factory=factory,
            project_repository=repository,
        )

        result = service.create_project("Test")

        factory.create.assert_called_once_with("Test")
        repository.create.assert_called_once_with(project)
        repository.save.assert_not_called()
        self.assertIs(result, project)

    def test_delete_project_delegates_without_save(self) -> None:
        repository = Mock()
        service = ProjectService(
            project_factory=Mock(spec=ProjectFactory),
            project_repository=repository,
        )

        service.delete_project("project-1", expected_version=2)

        repository.delete.assert_called_once_with(
            "project-1",
            expected_version=2,
        )
        repository.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
