from __future__ import annotations

import unittest
from abc import abstractmethod

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.persistence.records import ExecutionLogEntry
from application.ports.execution_log_store import ExecutionLogStore
from application.ports.project_repository import ProjectRepository
from domain.factories.project_factory import ProjectFactory


class ProjectRepositoryContractTests:
    """
    Shared behavioral contract for ProjectRepository port implementations.

    These tests verify aggregate semantics required of every adapter
    (in-memory, PostgreSQL, etc.). Adapter-specific behavior — such as
    transitional file-layout limitations — belongs in separate adapter tests.
    """

    repository: ProjectRepository

    @abstractmethod
    def build_repository(self) -> ProjectRepository:
        raise NotImplementedError

    def setUp(self) -> None:
        self.repository = self.build_repository()
        self.project_factory = ProjectFactory()

    def test_create_and_get_by_id(self) -> None:
        project = self.project_factory.create("Contract Project")

        self.repository.create(project)

        loaded = self.repository.get_by_id(project.id)

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.id, project.id)
        self.assertEqual(loaded.name, project.name)

    def test_save_after_create_increments_version(self) -> None:
        project = self.project_factory.create("Contract Project")

        self.repository.create(project)
        version = self.repository.save(project)

        self.assertEqual(version, 1)

    def test_create_rejects_duplicate_id(self) -> None:
        project = self.project_factory.create("Duplicate")

        self.repository.create(project)

        with self.assertRaises(DuplicateEntityError):
            self.repository.create(project)

    def test_save_rejects_missing_aggregate(self) -> None:
        project = self.project_factory.create("Missing")

        with self.assertRaises(EntityNotFoundError):
            self.repository.save(project)

    def test_get_by_id_returns_none_for_missing_project(self) -> None:
        self.assertIsNone(self.repository.get_by_id("missing-project"))

    def test_list_returns_created_projects(self) -> None:
        first = self.project_factory.create("First")
        second = self.project_factory.create("Second")

        self.repository.create(first)
        self.repository.create(second)

        projects = self.repository.list()

        self.assertEqual({project.id for project in projects}, {first.id, second.id})

    def test_delete_removes_project_with_matching_version(self) -> None:
        project = self.project_factory.create("Delete Me")

        self.repository.create(project)
        self.repository.delete(project.id, expected_version=0)

        self.assertIsNone(self.repository.get_by_id(project.id))
        self.assertEqual(self.repository.list(), [])

    def test_delete_missing_aggregate_raises(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.repository.delete("missing-project", expected_version=0)

    def test_delete_with_stale_expected_version_raises(self) -> None:
        project = self.project_factory.create("Stale Delete")

        self.repository.create(project)
        self.repository.save(project)

        with self.assertRaises(ConcurrentModificationError):
            self.repository.delete(project.id, expected_version=0)

    def test_save_with_stale_expected_version_raises(self) -> None:
        project = self.project_factory.create("Versioned")

        self.repository.create(project)
        self.repository.save(project)

        with self.assertRaises(ConcurrentModificationError):
            self.repository.save(project, expected_version=0)

    def test_save_with_matching_expected_version_succeeds(self) -> None:
        project = self.project_factory.create("Versioned")

        self.repository.create(project)
        first_version = self.repository.save(project)
        second_version = self.repository.save(
            project,
            expected_version=first_version,
        )

        self.assertEqual(second_version, first_version + 1)


class InMemoryProjectRepositoryContractTests(
    ProjectRepositoryContractTests,
    unittest.TestCase,
):
    def build_repository(self) -> ProjectRepository:
        from infrastructure.persistence.memory.in_memory_project_repository import (
            InMemoryProjectRepository,
        )

        return InMemoryProjectRepository()


class ExecutionLogStoreContractTests:
    """
    Shared behavioral contract for append-only ExecutionLogStore implementations.

    Verifies append semantics, idempotency, and query boundaries — not
    adapter-specific storage details.
    """

    store: ExecutionLogStore

    @abstractmethod
    def build_store(self) -> ExecutionLogStore:
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.build_store()

    def test_append_and_list_for_run(self) -> None:
        entry = ExecutionLogEntry(
            event_id="event-1",
            run_id="run-1",
            task_id="task-1",
            event_type="task.started",
            timestamp="2026-07-31T10:00:00+00:00",
            payload={"attempt_id": "attempt-1"},
        )

        self.store.append(entry)
        entries = self.store.list_for_run("run-1")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event_id, "event-1")

    def test_append_is_idempotent_by_event_id(self) -> None:
        entry = ExecutionLogEntry(
            event_id="event-dup",
            run_id="run-1",
            event_type="task.completed",
            timestamp="2026-07-31T10:00:00+00:00",
        )

        self.store.append(entry)
        self.store.append(entry)

        self.assertEqual(len(self.store.list_for_run("run-1")), 1)

    def test_list_for_task_filters_entries(self) -> None:
        self.store.append(
            ExecutionLogEntry(
                event_id="event-a",
                run_id="run-1",
                task_id="task-a",
                event_type="task.started",
                timestamp="2026-07-31T10:00:00+00:00",
            )
        )
        self.store.append(
            ExecutionLogEntry(
                event_id="event-b",
                run_id="run-1",
                task_id="task-b",
                event_type="task.started",
                timestamp="2026-07-31T10:00:01+00:00",
            )
        )

        entries = self.store.list_for_task("run-1", "task-a")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event_id, "event-a")


class InMemoryExecutionLogStoreContractTests(
    ExecutionLogStoreContractTests,
    unittest.TestCase,
):
    def build_store(self) -> ExecutionLogStore:
        from infrastructure.persistence.memory.in_memory_execution_log_store import (
            InMemoryExecutionLogStore,
        )

        return InMemoryExecutionLogStore()


if __name__ == "__main__":
    unittest.main()
