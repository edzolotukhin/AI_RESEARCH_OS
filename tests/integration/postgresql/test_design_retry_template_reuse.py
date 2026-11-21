from __future__ import annotations

from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.exceptions.structured_output_error import StructuredOutputError
from domain.ai.llm_response import LLMResponse
from domain.research_brief import ResearchBrief
from domain.workflow_status import WorkflowStatus
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class PostgreSQLDesignRetryTemplateReuseTests(PostgreSQLIntegrationTestCase):
    def test_failed_design_retry_reuses_immutable_template_without_republishing(self):
        llm = Mock()
        llm.generate.return_value = LLMResponse(content="{}")
        container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=llm),
        )
        self.addCleanup(container.shutdown)
        container.agency.initialize()

        project = container.project_service.create_project(
            "Design retry",
            owner_principal_id="owner",
            project_id="design-retry-project",
            selected_methods=("DESK",),
        )
        container.project_planning_service.save_brief(
            project,
            ResearchBrief(
                title="Population",
                business_question="How did population change?",
            ),
        )

        first = container.project_planning_service.schedule_design_generation(project)
        template = container.workflow_service.get_template(first.workflow_template_id)
        self.assertIsNotNone(template)

        with self.assertRaises(StructuredOutputError):
            container.worker_execution_service.drain_runnable_runs(
                "design-retry-worker", max_runs=1,
            )
        failed = container.workflow_service.get_workflow_run(first.id)
        self.assertEqual(failed.status, WorkflowStatus.FAILED)

        retry = container.project_planning_service.schedule_design_generation(
            container.project_service.get_project(project.id),
        )
        self.assertNotEqual(retry.id, first.id)
        self.assertEqual(retry.workflow_template_id, template.id)
        self.assertEqual(
            container.workflow_service.get_template(retry.workflow_template_id),
            template,
        )

        runs = container.workflow_service.list_workflow_runs_for_project(project.id)
        self.assertEqual({run.id for run in runs}, {first.id, retry.id})
        self.assertEqual(
            container.workflow_service.get_workflow_run(first.id).status,
            WorkflowStatus.FAILED,
        )
        self.assertEqual(
            len(container.workflow_service.list_templates_for_project(project.id)),
            1,
        )
