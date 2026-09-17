from __future__ import annotations

from domain.factories.project_factory import ProjectFactory
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class Pf02ProjectPlanningPersistenceTests(PostgreSQLIntegrationTestCase):
    def test_selection_design_and_approval_survive_repository_restart(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        repository = PostgreSQLProjectRepository(self.session_factory)
        project = ProjectFactory().create("PF-02 durable")
        project.owner_principal_id = "owner-pf02"
        project.selected_methods = ("DESK", "QUANTITATIVE")
        project.current_research_design = ResearchDesign(
            id="design-pf02",
            research_questions=(ResearchQuestion("rq-1", "What changed?"),),
            analysis_plan=("Compare supported evidence",),
            language="uk",
        )
        project.research_design_status = "APPROVED"
        project.research_design_input_fingerprint = "f" * 64
        project.research_design_approved_by = "owner-pf02"
        project.research_design_approved_at = "2026-09-17T12:00:00+00:00"
        repository.create(project)

        restarted = PostgreSQLProjectRepository(self.session_factory)
        loaded = restarted.get_by_id(project.id)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.selected_methods, project.selected_methods)
        self.assertEqual(loaded.current_research_design, project.current_research_design)
        self.assertEqual(loaded.research_design_status, "APPROVED")
        self.assertEqual(loaded.research_design_input_fingerprint, "f" * 64)
        self.assertEqual(loaded.research_design_approved_by, "owner-pf02")
        self.assertEqual(loaded.research_design_approved_at, project.research_design_approved_at)
