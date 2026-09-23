from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy.orm import Session

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from domain.research_brief import ResearchBrief
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    create_test_engine, integration_tests_enabled, postgresql_application_config,
    reset_schema,
)
from unittest import skipUnless


@skipUnless(integration_tests_enabled(), "Disposable PostgreSQL database required")
class ActivationTransactions(TestCase):
    def setUp(self):
        engine = create_test_engine()
        reset_schema(engine)
        self.addCleanup(engine.dispose)
        self.container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=True,
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
        )
        self.addCleanup(self.container.shutdown)

    def project(self, method):
        service = self.container.project_service
        project = service.create_project(
            "Atomic activation", owner_principal_id="owner",
            selected_methods=(method,),
        )
        planner = self.container.project_planning_service
        planner.save_brief(project, ResearchBrief(
            title="Study", business_question="What changed?",
            objectives=("Measure demand",), language="uk",
        ))
        planner.generate_design(service.get_project(project.id))
        project = service.get_project(project.id)
        planner.approve_design(
            project, actor_id="owner", expected_design_id=project.current_research_design.id,
        )
        return service.get_project(project.id)

    def test_quantitative_run_and_study_commit_together_and_replay(self):
        project = self.project("QUANTITATIVE")
        planner = self.container.project_planning_service
        study = planner.activate_quantitative(project, owner_id="owner")
        self.assertEqual(study.state, "WAITING_FOR_DATASET")
        self.assertEqual(
            planner.activate_quantitative(project, owner_id="owner"), study,
        )
        self.assertEqual(len(self.container.workflow_service.list_workflow_runs_for_project(project.id)), 1)
        self.assertEqual(len(self.container.quantitative_ui_service.state.list_for_run(
            study.run_id, project_id=project.id,
        )), 1)

    def test_quantitative_projection_failure_rolls_back_run(self):
        project = self.project("QUANTITATIVE")
        quant = self.container.quantitative_ui_service
        with patch.object(quant.state, "persist", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.container.project_planning_service.activate_quantitative(project, owner_id="owner")
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])

    def test_quantitative_authorization_and_design_failure_create_nothing(self):
        project = self.project("QUANTITATIVE")
        planner = self.container.project_planning_service
        with self.assertRaises(ValueError):
            planner.activate_quantitative(project, owner_id="foreign")
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])
        planner.add_method(project, "DESK")
        with self.assertRaises(ValueError):
            planner.activate_quantitative(project, owner_id="owner")
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])

    def test_quantitative_run_insertion_failure_creates_no_projection(self):
        project = self.project("QUANTITATIVE")
        workflow = self.container.workflow_service
        with patch.object(workflow, "create_workflow_run", side_effect=RuntimeError("run failed")):
            with self.assertRaisesRegex(RuntimeError, "run failed"):
                self.container.project_planning_service.activate_quantitative(project, owner_id="owner")
        self.assertEqual(workflow.list_workflow_runs_for_project(project.id), [])

    def test_commit_failure_rolls_back_quantitative_activation(self):
        project = self.project("QUANTITATIVE")
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                self.container.project_planning_service.activate_quantitative(project, owner_id="owner")
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])

    def test_concurrent_quantitative_activation_is_one_run(self):
        project = self.project("QUANTITATIVE")
        planner = self.container.project_planning_service
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(planner.activate_quantitative, project, owner_id="owner") for _ in range(2)]
            studies = [item.result(timeout=20) for item in futures]
        self.assertEqual(studies[0].study_id, studies[1].study_id)
        self.assertEqual(len(self.container.workflow_service.list_workflow_runs_for_project(project.id)), 1)

    def test_desk_run_is_pollable_after_commit_and_replayed(self):
        project = self.project("DESK")
        planner = self.container.project_planning_service
        run = planner.activate_desk(project)
        self.assertEqual(planner.activate_desk(project).id, run.id)
        execution = self.container.worker_execution_service._execution_port
        now = datetime.now(timezone.utc)
        claimed = execution.claim_next_runnable(
            worker_id="prf05a-test", now=now, lease_until=now + timedelta(seconds=30),
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.run_id, run.id)

    def test_desk_run_insertion_failure_rolls_back_project_change(self):
        project = self.project("DESK")
        initial_version = project.persistence_version
        workflow = self.container.workflow_service
        with patch.object(workflow, "create_workflow_run", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.container.project_planning_service.activate_desk(project)
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])
        self.assertEqual(self.container.project_service.get_project(project.id).persistence_version, initial_version)

    def test_concurrent_desk_activation_is_one_run(self):
        project = self.project("DESK")
        planner = self.container.project_planning_service
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(planner.activate_desk, project) for _ in range(2)]
            runs = [item.result(timeout=20) for item in futures]
        self.assertEqual(runs[0].id, runs[1].id)
        self.assertEqual(len(self.container.workflow_service.list_workflow_runs_for_project(project.id)), 1)

    def test_failed_notification_does_not_lose_committed_desk_run(self):
        project = self.project("DESK")
        queue = self.container.agency._durable_workflow_service._run_queue
        with patch.object(queue, "notify_runnable", side_effect=RuntimeError("queue unavailable")):
            run = self.container.project_planning_service.activate_desk(project)
        now = datetime.now(timezone.utc)
        claim = self.container.worker_execution_service._execution_port.claim_next_runnable(
            worker_id="recovery-test", now=now,
            lease_until=now + timedelta(seconds=30),
        )
        self.assertEqual(claim.run_id, run.id)

    def test_desk_notification_is_deferred_until_commit(self):
        project = self.project("DESK")
        durable = self.container.agency._durable_workflow_service
        delivered = []
        queue = durable._run_queue
        with patch.object(queue, "notify_runnable", side_effect=lambda run_id: delivered.append(run_id)):
            with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
                with self.assertRaisesRegex(RuntimeError, "commit failure"):
                    self.container.project_planning_service.activate_desk(project)
            self.assertEqual(delivered, [])
            self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project.id), [])
            run = self.container.project_planning_service.activate_desk(project)
            self.assertEqual(delivered, [run.id])
