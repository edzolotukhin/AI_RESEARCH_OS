from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock

from application.services.project_planning_service import ProjectPlanningService
from domain.project import Project
from domain.research_brief import (
    BRIEF_FINGERPRINT_V1,
    BRIEF_FINGERPRINT_V2,
    ResearchBrief,
)


class ObjectiveRegistryV2Tests(TestCase):
    def _service(self):
        workflows = Mock()
        workflows.list_workflow_runs_for_project.return_value = []
        return ProjectPlanningService(
            project_service=Mock(), workflow_service=workflows,
            planner_agent=Mock(), workflow_mapper=Mock(), agency=Mock(),
            quantitative_ui_service=Mock(), durable_workflow_service=None,
        )

    def test_new_saved_brief_materializes_deterministic_v2_registry(self):
        brief = ResearchBrief(
            title="Population", business_question="How did it change?",
            objectives=("Measure population", "Compare annual change"),
        )
        project = Project("project", "Test project")
        service = self._service()

        service.save_brief(project, brief)

        self.assertEqual(project.research_brief.fingerprint_version, BRIEF_FINGERPRINT_V2)
        self.assertEqual(
            tuple(item.objective_id for item in project.research_brief.objective_registry),
            ("obj-001", "obj-002"),
        )
        self.assertEqual(
            tuple(item.ordinal for item in project.research_brief.objective_registry),
            (1, 2),
        )
        self.assertEqual(
            ProjectPlanningService.input_fingerprint(project.research_brief, ("DESK",)),
            ProjectPlanningService.input_fingerprint(
                project.research_brief, ("DESK",)
            ),
        )

    def test_text_or_order_change_changes_v2_fingerprint(self):
        service = self._service()
        first = ResearchBrief("P", "Q", objectives=("A", "B")).materialize_objective_registry()
        changed = ResearchBrief("P", "Q", objectives=("A changed", "B")).materialize_objective_registry()
        reordered = ResearchBrief("P", "Q", objectives=("B", "A")).materialize_objective_registry()

        fingerprints = {
            service.input_fingerprint(item, ("DESK",))
            for item in (first, changed, reordered)
        }
        self.assertEqual(len(fingerprints), 3)
        self.assertTrue(all(value.startswith("v2:") for value in fingerprints))

    def test_legacy_reload_preserves_v1_identity_and_shape(self):
        legacy = ResearchBrief(
            "P", "Q", objectives=("A",), fingerprint_version=BRIEF_FINGERPRINT_V1,
        )
        payload = legacy.to_dict()
        restored = ResearchBrief.from_dict(payload)

        self.assertIsNotNone(restored)
        self.assertIsNone(restored.objective_registry)
        self.assertEqual(restored.fingerprint_version, BRIEF_FINGERPRINT_V1)
        self.assertEqual(restored.to_dict(), payload)
        self.assertFalse(
            ProjectPlanningService.input_fingerprint(restored, ("DESK",)).startswith("v2:")
        )

    def test_registry_survives_serialization_reload(self):
        brief = ResearchBrief("P", "Q", objectives=("A", "B")).materialize_objective_registry()
        restored = ResearchBrief.from_dict(brief.to_dict())

        self.assertEqual(restored, brief)
        self.assertEqual(
            [item.text_fingerprint for item in restored.objective_registry],
            [item.text_fingerprint for item in brief.objective_registry],
        )
