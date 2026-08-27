import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from agency.agency import Agency
from application.composition_root import create_application, create_application_container
from application.config import ApplicationConfig, ApplicationOverrides

from domain.ai.llm_response import LLMResponse
from tests.fixtures.research_brief import sample_research_brief

from application.ports.project_repository import ProjectRepository
from application.persistence.exceptions import EntityNotFoundError
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.memory.in_memory_project_repository import InMemoryProjectRepository
from infrastructure.persistence.memory.in_memory_workflow_run_repository import InMemoryWorkflowRunRepository
from application.services.project_service import ProjectService
from application.quantitative.state_persistence import QuantitativePersistenceError
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import VALID_PLANNER_JSON


class CompositionRootTests(unittest.TestCase):

    def test_create_application_returns_agency(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agency = create_application(
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
            ),
        )

        self.assertIsInstance(agency, Agency)

    def test_create_application_uses_llm_client_override_without_openai(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                ),
            )

            agency.initialize()

            project = agency.create_project("Brand Health 2026")
            project.research_brief = sample_research_brief()

            context = agency.start_research(project)

            self.assertIsInstance(context, WorkflowContext)
            mock_llm.generate.assert_called()
            self.assertTrue(any(Path(temp_dir).iterdir()))

    def test_quantitative_repository_override_survives_production_container_reconstruction(self):
        shared = InMemoryQuantitativeStateRepository()
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        def container(repository=None, *, backend="memory"):
            return create_application_container(
                config=ApplicationConfig(
                    projects_root=self._temp_dir,
                    persistence_backend=backend,
                    deterministic_stage_executors=True,
                    search_provider="deterministic",
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                    quantitative_state_repository=repository,
                ),
            )

        with tempfile.TemporaryDirectory() as root:
            self._temp_dir = root
            first = container(shared)
            first_designs = first.quantitative_authority_finalization_service._designs
            brief = first_designs.create_brief(
                brief_id="restart-brief", version_id="restart-brief-v1",
                project_id="restart-project", run_id="restart-run",
                title="Offline restart study", business_context="Synthetic context.",
                business_problem="Prove production composition restart.",
                decision_context="Accept the composition boundary.",
                research_purpose="Verify exact typed authority reload.",
                intended_audience=("Engineering",), target_deliverables=("Acceptance",),
                constraints=("No external persistence",), provenance="TEST_AUTHORED",
                created_at="2026-08-27T00:00:00Z", created_by="tester",
            )
            first.shutdown()

            second = container(shared)
            second_designs = second.quantitative_authority_finalization_service._designs
            reloaded = second_designs._repository.get_brief(
                brief.version_id, project_id="restart-project",
            )
            self.assertIsNot(first, second)
            self.assertIsNot(first_designs, second_designs)
            self.assertEqual(brief, reloaded)
            self.assertEqual(brief.fingerprint, reloaded.fingerprint)
            self.assertIsNone(second_designs._repository.get_brief(
                brief.version_id, project_id="wrong-project",
            ))
            second.shutdown()

            fresh = container(InMemoryQuantitativeStateRepository())
            self.assertIsNone(fresh.quantitative_authority_finalization_service._designs._repository.get_brief(
                brief.version_id, project_id="restart-project",
            ))
            fresh.shutdown()

            default_a = container()
            default_a.quantitative_authority_finalization_service._designs.create_brief(
                brief_id="default", version_id="default-v1", project_id="p", run_id="r",
                title="Default memory", business_context="Context.", business_problem="Problem.",
                decision_context="Decision.", research_purpose="Purpose.",
                intended_audience=("Audience",), target_deliverables=("Report",),
                constraints=(), provenance="TEST_AUTHORED", created_at="t", created_by="tester",
            )
            default_a.shutdown()
            default_b = container()
            self.assertIsNone(default_b.quantitative_authority_finalization_service._designs._repository.get_brief(
                "default-v1", project_id="p",
            ))
            default_b.shutdown()

            file_default = container(backend="file")
            self.assertIsNone(file_default.quantitative_authority_finalization_service)
            file_default.shutdown()

            record = shared._records[brief.version_id]
            shared._records[brief.version_id] = replace(record, payload_checksum="corrupt")
            corrupt = container(shared)
            with self.assertRaises(QuantitativePersistenceError):
                corrupt.quantitative_authority_finalization_service._designs._repository.get_brief(
                    brief.version_id, project_id="restart-project",
                )
            corrupt.shutdown()
    def test_scope_repository_overrides_survive_production_container_reconstruction(self):
        projects = InMemoryProjectRepository()
        runs = InMemoryWorkflowRunRepository()
        quantitative = InMemoryQuantitativeStateRepository()
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        with tempfile.TemporaryDirectory() as root:
            def build(project_repository, workflow_run_repository, quantitative_repository):
                return create_application_container(
                    config=ApplicationConfig(
                        projects_root=root, persistence_backend="memory",
                        deterministic_stage_executors=True, search_provider="deterministic",
                    ),
                    overrides=ApplicationOverrides(
                        llm_client=mock_llm,
                        project_repository=project_repository,
                        workflow_run_repository=workflow_run_repository,
                        quantitative_state_repository=quantitative_repository,
                    ),
                )

            first = build(projects, runs, quantitative)
            project = first.project_service.create_project("Restart scope")
            run = first.workflow_service.create_workflow_run(
                WorkflowTemplate(id="restart-template", name="Restart"),
                project_id=project.id, run_id="restart-run",
            )
            run.ready()
            run.start()
            run.complete()
            first.workflow_service.save_workflow_run(run, expected_version=0)
            brief = first.quantitative_authority_finalization_service._designs.create_brief(
                brief_id="scope-brief", version_id="scope-brief-v1",
                project_id=project.id, run_id=run.id,
                title="Scope restart", business_context="Synthetic context.",
                business_problem="Persist the complete authority scope.",
                decision_context="Accept restart composition.",
                research_purpose="Verify Project, run, and Quantitative reload.",
                intended_audience=("Engineering",), target_deliverables=("Acceptance",),
                constraints=("Offline",), provenance="TEST_AUTHORED",
                created_at="2026-08-27T00:00:00Z", created_by="tester",
            )
            first_project_service = first.project_service
            first_workflow_service = first.workflow_service
            first_rl = first.quantitative_authority_finalization_service
            first.shutdown()

            second = build(projects, runs, quantitative)
            reloaded_project = second.project_service.get_project(project.id)
            reloaded_run = second.workflow_service.get_workflow_run(run.id)
            reloaded_brief = second.quantitative_authority_finalization_service._designs._repository.get_brief(
                brief.version_id, project_id=project.id,
            )
            second.quantitative_authority_finalization_service._scope(project.id, run.id)
            self.assertIsNot(first, second)
            self.assertIsNot(first_project_service, second.project_service)
            self.assertIsNot(first_workflow_service, second.workflow_service)
            self.assertIsNot(first_rl, second.quantitative_authority_finalization_service)
            self.assertEqual(project.id, reloaded_project.id)
            self.assertEqual((run.id, project.id), (reloaded_run.id, reloaded_run.project_id))
            self.assertEqual((brief.version_id, brief.fingerprint),
                             (reloaded_brief.version_id, reloaded_brief.fingerprint))
            self.assertEqual([], second.workflow_service.list_workflow_runs_for_project("wrong-project"))
            self.assertIsNone(second.quantitative_authority_finalization_service._designs._repository.get_brief(
                brief.version_id, project_id="wrong-project",
            ))
            second.shutdown()

            fresh = build(
                InMemoryProjectRepository(), InMemoryWorkflowRunRepository(),
                InMemoryQuantitativeStateRepository(),
            )
            with self.assertRaises(EntityNotFoundError):
                fresh.project_service.get_project(project.id)
            with self.assertRaises(EntityNotFoundError):
                fresh.workflow_service.get_workflow_run(run.id)
            self.assertIsNone(fresh.quantitative_authority_finalization_service._designs._repository.get_brief(
                brief.version_id, project_id=project.id,
            ))
            fresh.shutdown()
    def test_create_application_uses_project_repository_override(self):
        custom_repository = Mock(spec=ProjectRepository)

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agency = create_application(
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
                project_repository=custom_repository,
            ),
        )

        project = agency.create_project("Test Project")

        custom_repository.create.assert_called_once_with(project)
        custom_repository.save.assert_not_called()

    def test_create_application_uses_project_service_override(self):
        custom_service = Mock(spec=ProjectService)
        expected_project = Mock()
        custom_service.create_project.return_value = expected_project

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agency = create_application(
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
                project_service=custom_service,
            ),
        )

        result = agency.create_project("Override Project")

        custom_service.create_project.assert_called_once_with(
            "Override Project",
            owner_principal_id=None,
        )
        self.assertIs(result, expected_project)


if __name__ == "__main__":
    unittest.main()
