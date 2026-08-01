from __future__ import annotations

import tempfile
import unittest

from domain.factories.project_factory import ProjectFactory
from tests.fixtures.research_brief import sample_research_brief

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

    def test_research_brief_round_trip(self) -> None:
        project = self.project_factory.create("Brief Round-Trip")
        project.research_brief = sample_research_brief()

        self.repository.create(project)
        loaded = self.repository.get_by_id(project.id)

        assert loaded is not None
        assert loaded.research_brief == project.research_brief


if __name__ == "__main__":
    unittest.main()
