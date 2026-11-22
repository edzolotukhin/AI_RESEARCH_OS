from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.exceptions.structured_output_error import StructuredOutputError
from application.services.project_planning_service import ProjectPlanningService
from application.planner.objective_coverage import evaluate_objective_coverage
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from domain.ai.llm_response import LLMResponse
from domain.project import Project
from domain.research_brief import BRIEF_FINGERPRINT_V1, ResearchBrief
from domain.workflow_status import WorkflowStatus
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class PostgreSQLObjectiveRegistryV2Tests(PostgreSQLIntegrationTestCase):
    def test_planner_worker_persists_and_reloads_objective_ids_design(self):
        planner_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=planner_llm),
        )
        self.addCleanup(container.shutdown)
        container.agency.initialize()

        project = container.project_service.create_project(
            "Registry v2 Design", owner_principal_id="owner", project_id=str(uuid4()),
            selected_methods=("DESK",),
        )
        container.project_planning_service.save_brief(
            project,
            ResearchBrief(
                "Population", "How did population change?",
                objectives=("Measure population", "Compare annual change"),
            ),
        )
        queued = container.project_planning_service.schedule_design_generation(
            container.project_service.get_project(project.id)
        )
        template = container.workflow_service.get_template(queued.workflow_template_id)
        container.worker_execution_service.drain_runnable_runs(
            "registry-v2-worker", max_runs=1,
        )
        persisted = container.project_service.get_project(project.id)
        design = persisted.current_research_design
        self.assertIsNotNone(design)
        self.assertEqual(design.objective_reference_contract, "objective_ids_v1")
        self.assertEqual(design.brief_fingerprint[:3], "v2:")
        self.assertEqual(
            design.objective_registry_identity,
            persisted.research_brief.objective_registry_identity,
        )
        refs = {
            ref for question in design.research_questions
            for ref in question.objective_refs
        }
        self.assertTrue({"obj-001", "obj-002"}.issubset(refs))
        self.assertIsNone(
            evaluate_objective_coverage(persisted.research_brief, design)
        )
        self.assertEqual(
            len(container.workflow_service.list_templates_for_project(project.id)), 1
        )

        fresh = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=planner_llm),
        )
        self.addCleanup(fresh.shutdown)
        fresh.agency.initialize()
        reloaded = fresh.project_service.get_project(project.id)
        reloaded_design = reloaded.current_research_design
        self.assertIsNotNone(reloaded_design)
        self.assertEqual(
            reloaded_design.objective_reference_contract,
            design.objective_reference_contract,
        )
        self.assertEqual(reloaded_design.brief_fingerprint, design.brief_fingerprint)
        self.assertEqual(
            reloaded_design.objective_registry_identity,
            design.objective_registry_identity,
        )
        self.assertEqual(
            tuple(ref for question in reloaded_design.research_questions for ref in question.objective_refs),
            tuple(ref for question in design.research_questions for ref in question.objective_refs),
        )
        self.assertIsNone(
            evaluate_objective_coverage(reloaded.research_brief, reloaded_design)
        )
        self.assertEqual(
            fresh.workflow_service.get_template(template.id),
            container.workflow_service.get_template(template.id),
        )

    def test_registry_reload_legacy_identity_and_failed_v1_retry(self):
        invalid_planner = Mock()
        invalid_planner.generate.return_value = LLMResponse(
            content="{}",
            finish_reason="stop",
            output_tokens=1,
            max_output_tokens=8192,
            reasoning_tokens=0,
            configured_reasoning_effort="minimal",
        )
        container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=invalid_planner),
        )
        self.addCleanup(container.shutdown)
        container.agency.initialize()

        v2_project = container.project_service.create_project(
            "Registry v2", owner_principal_id="owner", project_id=str(uuid4()),
            selected_methods=("DESK",),
        )
        v2_brief = ResearchBrief(
            "Population", "How did population change?",
            objectives=("Measure population", "Compare annual change"),
        )
        container.project_planning_service.save_brief(v2_project, v2_brief)
        persisted_v2 = container.project_service.get_project(v2_project.id).research_brief
        v2_fingerprint = ProjectPlanningService.input_fingerprint(
            persisted_v2, ("DESK",)
        )

        fresh = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=invalid_planner),
        )
        self.addCleanup(fresh.shutdown)
        fresh.agency.initialize()
        reloaded_v2 = fresh.project_service.get_project(v2_project.id).research_brief
        self.assertEqual(reloaded_v2, persisted_v2)
        self.assertEqual(
            [(item.objective_id, item.ordinal, item.text, item.text_fingerprint)
             for item in reloaded_v2.objective_registry],
            [(item.objective_id, item.ordinal, item.text, item.text_fingerprint)
             for item in persisted_v2.objective_registry],
        )
        self.assertEqual(
            ProjectPlanningService.input_fingerprint(reloaded_v2, ("DESK",)),
            v2_fingerprint,
        )

        legacy_project = fresh.project_service.create_project(
            "Legacy v1", owner_principal_id="owner", project_id=str(uuid4()),
            selected_methods=("DESK",),
        )
        legacy_brief = ResearchBrief(
            "Legacy", "Legacy question", objectives=("Legacy objective",),
            fingerprint_version=BRIEF_FINGERPRINT_V1,
        )
        legacy_fingerprint = ProjectPlanningService.input_fingerprint(
            legacy_brief, ("DESK",)
        )
        legacy_project.research_brief = legacy_brief
        legacy_project.research_design_input_fingerprint = legacy_fingerprint
        fresh.project_service.save_project(legacy_project)

        reloaded_legacy = fresh.project_service.get_project(legacy_project.id)
        self.assertIsNone(reloaded_legacy.research_brief.objective_registry)
        self.assertEqual(
            reloaded_legacy.research_design_input_fingerprint, legacy_fingerprint
        )
        self.assertEqual(
            ProjectPlanningService.input_fingerprint(
                reloaded_legacy.research_brief, ("DESK",)
            ),
            legacy_fingerprint,
        )

        first = fresh.project_planning_service.schedule_design_generation(
            reloaded_legacy
        )
        template = fresh.workflow_service.get_template(first.workflow_template_id)
        with self.assertRaises(StructuredOutputError):
            fresh.worker_execution_service.drain_runnable_runs(
                "registry-v2-worker", max_runs=1
            )
        failed = fresh.workflow_service.get_workflow_run(first.id)
        self.assertEqual(failed.status, WorkflowStatus.FAILED)

        retry = fresh.project_planning_service.schedule_design_generation(
            fresh.project_service.get_project(legacy_project.id)
        )
        self.assertNotEqual(retry.id, first.id)
        self.assertEqual(retry.workflow_template_id, template.id)
        self.assertEqual(
            fresh.workflow_service.get_template(retry.workflow_template_id), template
        )
        self.assertEqual(
            len(fresh.workflow_service.list_templates_for_project(legacy_project.id)),
            1,
        )
