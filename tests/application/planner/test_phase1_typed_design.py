from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

from application.parsers.research_design_parser import ResearchDesignParser
from application.factories.research_design_factory import ResearchDesignFactory
from application.research.design_validator import validate_subject_for_approval
from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.mappers.workflow_template_mapper import (
    workflow_template_to_model, workflow_template_from_model,
)
from tests.application.analysis.test_executable_derivations import derived_design


class TypedDesignTests(unittest.TestCase):
    def test_planner_factory_frozen_mapper_preserves_all_need_semantics(self):
        original = derived_design()
        payload = original.to_dict()
        actual = ResearchDesignFactory().create(
            ResearchDesignParser().parse(payload), research_subject=original.research_subject,
        )
        self.assertEqual(actual.information_needs, original.information_needs)
        template = WorkflowTemplate("typed", "Typed", (), research_design_snapshot=actual)
        model = workflow_template_to_model(
            template, project_id="project", created_at=datetime.now(timezone.utc),
        )
        loaded = workflow_template_from_model(model).research_design_snapshot
        self.assertEqual(loaded.to_dict(), actual.to_dict())
        self.assertEqual(loaded.information_needs[0].evidence_coverage.required_unit, "persons")

    def test_new_numeric_design_requires_authoritative_requirements_before_approval(self):
        original = derived_design()
        need = original.information_needs[0]
        for coverage in (None, replace(need.evidence_coverage, required_metric=""),
                         replace(need.evidence_coverage, required_periods=()),
                         replace(need.evidence_coverage, required_unit="", _legacy_required_unit_omitted=True)):
            with self.subTest(coverage=coverage):
                model = replace(original, information_needs=(replace(need, evidence_coverage=coverage),))
                with self.assertRaisesRegex(ValidationError, "numeric_requirements_unavailable"):
                    validate_subject_for_approval(model)

    def test_legacy_snapshot_is_loadable_without_inventing_coverage(self):
        payload = derived_design().to_dict()
        payload["information_needs"] = payload["information_needs"][:1]
        del payload["information_needs"][0]["evidence_coverage"]
        loaded = ResearchDesign.from_dict(payload)
        self.assertIsNone(loaded.information_needs[0].evidence_coverage)
        self.assertEqual(loaded.to_dict(), payload)

    def test_valid_typed_numeric_design_can_be_approved(self):
        validate_subject_for_approval(derived_design())

    def test_approval_service_rejects_incomplete_design_before_save(self):
        from application.services.project_planning_service import ProjectPlanningService, ProjectPlanningError
        from domain.project import Project

        service = ProjectPlanningService(
            project_service=Mock(), workflow_service=Mock(), planner_agent=None,
            workflow_mapper=None, agency=None, quantitative_ui_service=None,
        )
        original = derived_design()
        invalid = replace(original, information_needs=(replace(
            original.information_needs[0], evidence_coverage=None),),
            source_strategy=("Official statistics",), analysis_plan=("Analyze",),
            deliverable_plan=("Report",))
        project = Project("project", "Phase 1", selected_methods=("DESK",))
        project.current_research_design = invalid
        project.research_design_input_fingerprint = service.input_fingerprint(None, ("DESK",))
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_requirements_unavailable"):
            service.approve_design(project, actor_id="reviewer", expected_design_id=invalid.id)
        service.projects.save_project.assert_not_called()
