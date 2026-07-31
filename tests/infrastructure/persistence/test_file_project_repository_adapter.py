from __future__ import annotations

import tempfile
import unittest

from domain.factories.project_factory import ProjectFactory

from infrastructure.persistence.file.file_project_repository import (
    FileProjectRepository,
)


class FileProjectRepositoryAdapterTests(unittest.TestCase):
    """
    Adapter-specific tests for the transitional FileProjectRepository.

    These tests verify legacy file-layout behavior. They are **not** part of
    the generic ProjectRepository port contract because this adapter does not
    support complete aggregate round-trip. See adapter docstring and backlog
    item: Full Project aggregate mapping (PF-03).
    """

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = FileProjectRepository(
            projects_root=self._temp_dir.name,
        )
        self.project_factory = ProjectFactory()

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_create_and_load_core_fields(self) -> None:
        project = self.project_factory.create("File Adapter Project")

        self.repository.create(project)

        loaded = self.repository.get_by_id(project.id)

        assert loaded is not None
        self.assertEqual(loaded.id, project.id)
        self.assertEqual(loaded.name, project.name)

    def test_does_not_restore_nested_optional_fields(self) -> None:
        """Documents transitional limitation — full mapping deferred to PF-03."""
        project = self.project_factory.create("Partial Round-Trip")
        project.status = "research_design"

        self.repository.create(project)
        self.repository.save(project)

        loaded = self.repository.get_by_id(project.id)

        assert loaded is not None
        self.assertEqual(loaded.status, "research_design")
        self.assertIsNone(loaded.brief)
        self.assertEqual(loaded.runs, [])


if __name__ == "__main__":
    unittest.main()
