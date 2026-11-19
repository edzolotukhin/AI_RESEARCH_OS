from __future__ import annotations

from domain.factories.project_factory import ProjectFactory
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    EvidenceCoverageContract,
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from application.services.project_planning_service import (
    NumericIntentConfirmationEntry,
    ProjectPlanningService,
)
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

    def test_numeric_intent_confirmation_provenance_survives_postgresql_reload(self):
        from unittest.mock import Mock
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        repository = PostgreSQLProjectRepository(self.session_factory)
        project = ProjectFactory().create("P1 confirmation provenance")
        project.owner_principal_id = "owner-p1"
        project.selected_methods = ("QUANTITATIVE",)
        project.current_research_design = ResearchDesign(
            "design-source",
            (ResearchQuestion("rq", "What should be measured?"),),
            (
                InformationNeed(
                    "numeric", "rq", "Measured outcome", geography="Ukraine",
                    evidence_expectation=EvidenceExpectation(
                        EvidenceNature.MIXED,
                        required_aspects=("measurement",),
                    ),
                ),
                InformationNeed(
                    "context", "rq", "Methodological context",
                    evidence_expectation=EvidenceExpectation(
                        EvidenceNature.QUALITATIVE,
                        required_aspects=("methodology",),
                    ),
                ),
            ),
            source_strategy=("Authoritative sources",),
            analysis_plan=("Analyze confirmed evidence",),
            deliverable_plan=("Research report",),
        )
        project.research_design_status = "DRAFT"
        service = ProjectPlanningService(
            project_service=Mock(), workflow_service=Mock(), planner_agent=None,
            workflow_mapper=None, agency=None, quantitative_ui_service=None,
        )
        project.research_design_input_fingerprint = service.input_fingerprint(
            None, ("QUANTITATIVE",),
        )
        confirmed = service.confirm_numeric_intent(
            project,
            actor_id="owner-p1",
            expected_design_id="design-source",
            entries={
                "numeric": NumericIntentConfirmationEntry(True, EvidenceCoverageContract(
                    required_metric="Population",
                    required_unit="persons",
                    required_periods=("2019", "2020", "2021"),
                    geography="Ukraine",
                )),
                "context": NumericIntentConfirmationEntry(False),
            },
        )
        repository.create(project)

        loaded = PostgreSQLProjectRepository(self.session_factory).get_by_id(project.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.current_research_design, confirmed)
        self.assertEqual(
            loaded.current_research_design.numeric_intent_confirmation.confirmed_by,
            "owner-p1",
        )
        self.assertEqual(
            loaded.current_research_design.numeric_intent_confirmation.integrity_digest,
            confirmed.numeric_intent_confirmation.integrity_digest,
        )
