"""PostgreSQL durability regression for P1-05 research loop progress checkpoints."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_quality.deterministic_targeted_research_runner import (
    DeterministicTargetedResearchRunner,
)
from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.research_quality_factory import (
    build_research_readiness_service,
)
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.runtime.interrupted_task_recovery import recover_interrupted_running_tasks
from application.runtime.task_result_codec import (
    capture_task_progress,
    is_progress_checkpoint,
    restore_runtime_state,
)
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
    PostgreSQLExecutionLogStore,
)

from runtime.workflow_context import WorkflowContext

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class SimulatedWorkerCrash(RuntimeError):
    """Simulates abrupt worker loss mid-readiness-task."""


_PROVIDER_TARGETS: list[str] = []


class _TrackingTargetedResearchRunner:
    """Records targeted need ids across runner instances for resume verification."""

    def __init__(
        self,
        *,
        source_repository,
        evidence_repository,
        crash_before_need_id: str | None = None,
    ) -> None:
        self._inner = DeterministicTargetedResearchRunner(
            source_repository=source_repository,
            evidence_repository=evidence_repository,
        )
        self._crash_before_need_id = crash_before_need_id

    def run(
        self,
        context: WorkflowContext,
        request: TargetedResearchRequest,
    ):
        _PROVIDER_TARGETS.append(request.information_need_id)
        if (
            self._crash_before_need_id is not None
            and request.information_need_id == self._crash_before_need_id
        ):
            raise SimulatedWorkerCrash(
                "simulated worker crash before second provider call",
            )
        return self._inner.run(context, request)


def _two_need_design() -> ResearchDesign:
    return ResearchDesign(
        id="pg-loop-design",
        research_questions=(
            ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Need one",
            ),
            InformationNeed(
                id="in-2",
                research_question_id="rq-2",
                description="Need two",
            ),
        ),
    )


def _missing_two_need_result() -> ResearchReadinessResult:
    assessments = (
        InformationNeedAssessment(
            information_need_id="in-1",
            research_question_id="rq-1",
            status=SufficiencyStatus.MISSING,
            evidence_count=0,
            gap_types=(GapType.NO_EVIDENCE,),
            reason="Missing.",
        ),
        InformationNeedAssessment(
            information_need_id="in-2",
            research_question_id="rq-2",
            status=SufficiencyStatus.MISSING,
            evidence_count=0,
            gap_types=(GapType.NO_EVIDENCE,),
            reason="Missing.",
        ),
    )
    return ResearchReadinessResult(
        research_question_assessments=(
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(assessments[0],),
                ready_for_analysis=False,
                blocking_information_need_ids=("in-1",),
            ),
            ResearchReadinessAssessment(
                research_question_id="rq-2",
                information_need_assessments=(assessments[1],),
                ready_for_analysis=False,
                blocking_information_need_ids=("in-2",),
            ),
        ),
        ready_for_analysis=False,
        blocking_research_question_ids=("rq-1", "rq-2"),
        blocking_information_need_ids=("in-1", "in-2"),
        targeted_research_required=True,
    )


class _StaticTwoNeedEvaluator:
    def evaluate(self, *, design: ResearchDesign, evidence):
        return _missing_two_need_result()


class ResearchLoopProgressCheckpointPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_progress_checkpoint_survives_interrupt_and_skips_completed_iteration(self) -> None:
        _PROVIDER_TARGETS.clear()

        config = postgresql_application_config(
            search_provider="deterministic",
            evidence_extractor="deterministic",
            research_sufficiency_assessor="deterministic",
        )
        container = create_application_container(config=config)
        self.addCleanup(container.shutdown)

        project = container.project_service.create_project("PG Loop Durability")
        design = _two_need_design()
        template = ResearchDesignWorkflowMapper().from_research_design(design, project)
        container.workflow_service.publish_template_snapshot(
            template,
            project_id=project.id,
        )
        workflow_run = container.workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="pg-loop-progress-recovery",
        )

        readiness_task = next(
            task
            for task in workflow_run.tasks
            if task.definition_id == "task-assess-research-readiness"
        )
        for task in workflow_run.tasks:
            if task.id == readiness_task.id:
                continue
            task.skip()
        readiness_task.ready()
        readiness_task.start()
        workflow_run.ready()
        workflow_run.start()

        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        service = build_research_readiness_service(
            config=config,
            overrides=ApplicationOverrides(
                source_repository=source_repo,
                evidence_repository=evidence_repo,
                targeted_research_runner=_TrackingTargetedResearchRunner(
                    source_repository=source_repo,
                    evidence_repository=evidence_repo,
                    crash_before_need_id="in-2",
                ),
                research_sufficiency_evaluator=_StaticTwoNeedEvaluator(),
            ),
            evidence_repository=evidence_repo,
            source_repository=source_repo,
            llm_client=None,
        )

        context = WorkflowContext(
            project=project,
            workflow_template=template,
            workflow_run=workflow_run,
            current_task=readiness_task,
        )
        audit = WorkflowExecutionAudit(
            PostgreSQLExecutionLogStore(self.session_factory),
        )
        persister = WorkflowRuntimePersister(
            workflow_service=container.workflow_service,
            audit=audit,
            run_id=workflow_run.id,
            initial_version=0,
        )
        context.services[CHECKPOINT_SERVICE_KEY] = persister
        persister.on_task_running(context)

        executor = ResearchReadinessExecutor(research_readiness_service=service)
        with self.assertRaises(SimulatedWorkerCrash):
            executor.run(context)

        task_results = {
            readiness_task.id: capture_task_progress(context, readiness_task.id),
        }
        self.assertTrue(is_progress_checkpoint(task_results[readiness_task.id]))
        loop_state = task_results[readiness_task.id]["shared_state"][SHARED_LOOP_STATE_KEY]
        self.assertEqual(loop_state["research_loop_count"], 1)
        self.assertEqual(len(loop_state["history"]), 1)
        self.assertEqual(
            loop_state["history"][0]["targeted_need_ids"],
            ["in-1"],
        )

        version = container.workflow_service.get_workflow_run_version(workflow_run.id)
        version = container.workflow_service.save_workflow_run(
            workflow_run,
            expected_version=version,
            task_results=task_results,
        )
        self.assertGreater(version, 0)
        self.assertEqual(_PROVIDER_TARGETS, ["in-1", "in-2"])
        self.assertEqual(_PROVIDER_TARGETS.count("in-1"), 1)

        reloaded_run = container.workflow_service.get_workflow_run(workflow_run.id)
        self.assertEqual(reloaded_run.status, WorkflowStatus.RUNNING)
        readiness_reloaded = next(
            task for task in reloaded_run.tasks if task.id == readiness_task.id
        )
        self.assertEqual(readiness_reloaded.status, TaskStatus.RUNNING)

        recovered = recover_interrupted_running_tasks(
            reloaded_run,
            container.workflow_service.get_task_results(workflow_run.id),
        )
        self.assertEqual(len(recovered), 1)
        self.assertEqual(readiness_reloaded.status, TaskStatus.READY)

        resume_context = WorkflowContext(
            project=project,
            workflow_template=template,
            workflow_run=reloaded_run,
            current_task=readiness_reloaded,
        )
        restore_runtime_state(
            resume_context,
            container.workflow_service.get_task_results(workflow_run.id),
        )
        readiness_reloaded.start()
        resume_persister = WorkflowRuntimePersister(
            workflow_service=container.workflow_service,
            audit=audit,
            run_id=workflow_run.id,
            initial_version=container.workflow_service.get_workflow_run_version(
                workflow_run.id,
            ),
            task_results=container.workflow_service.get_task_results(workflow_run.id),
        )
        resume_context.services[CHECKPOINT_SERVICE_KEY] = resume_persister

        resumed_service = build_research_readiness_service(
            config=config,
            overrides=ApplicationOverrides(
                source_repository=source_repo,
                evidence_repository=evidence_repo,
                targeted_research_runner=_TrackingTargetedResearchRunner(
                    source_repository=source_repo,
                    evidence_repository=evidence_repo,
                ),
                research_sufficiency_evaluator=_StaticTwoNeedEvaluator(),
            ),
            evidence_repository=evidence_repo,
            source_repository=source_repo,
            llm_client=None,
        )
        ResearchReadinessExecutor(research_readiness_service=resumed_service).run(
            resume_context,
        )

        self.assertEqual(_PROVIDER_TARGETS.count("in-1"), 1)
        self.assertIn("in-2", _PROVIDER_TARGETS)
        restored_loop = resume_context.read_shared(SHARED_LOOP_STATE_KEY)
        self.assertGreaterEqual(restored_loop["research_loop_count"], 1)
        self.assertEqual(restored_loop["history"][0]["targeted_need_ids"], ["in-1"])
        evidence = evidence_repo.list_for_project(
            project.id,
            workflow_run_id=workflow_run.id,
        )
        self.assertGreaterEqual(len(evidence), 1)
        self.assertIn("in-1", evidence[0].information_need_refs)


if __name__ == "__main__":
    unittest.main()
