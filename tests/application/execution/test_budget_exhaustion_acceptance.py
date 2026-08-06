"""LIVE ACCEPTANCE 02 regression tests for budget exhaustion and fail-fast."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.task import Task
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_template import WorkflowTemplate

from application.analysis.analysis_service import AnalysisService
from application.analysis.exceptions import AnalysisConfigurationError, AnalysisError
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    EXECUTION_BUDGET_KEY,
    RUN_USAGE_SUMMARY_KEY,
    ensure_run_budget,
    finalize_run_budget,
    set_execution_stage,
)
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.scheduling.scheduling_result import SchedulingResult
from application.task_scheduler import TaskScheduler
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.telemetry.run_usage_summary import RunUsageSummary
from application.workflow_engine import WorkflowEngine
from infrastructure.analysis.llm_analysis_engine import LlmAnalysisEngine
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)
from infrastructure.report.llm_report_engine import LlmReportEngine
from infrastructure.review.llm_review_engine import LlmReviewEngine
from runtime.workflow_context import WorkflowContext

from tests.infrastructure.review.test_llm_review_engine import _semantic_input


def _six_rq_design() -> ResearchDesign:
    questions = tuple(
        ResearchQuestion(
            id=f"RQ{i}",
            question=f"Question {i}?",
            objective_refs=(f"obj-{i}",),
            priority=i,
            rationale="",
        )
        for i in range(1, 7)
    )
    return ResearchDesign(
        id="design-budget",
        research_questions=questions,
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("batch by RQ",),
        deliverable_plan=("report",),
        assumptions=(),
        limitations=(),
        language="en",
    )


def _evidence_for_batches(*, run_id: str, design_id: str) -> list[Evidence]:
    items: list[Evidence] = []
    for index, rq in enumerate(
        ("RQ1", "RQ1", "RQ2", "RQ2", "RQ3", "RQ3", "RQ4", "RQ4", "RQ5", "RQ5", "RQ6", "RQ6"),
        start=1,
    ):
        items.append(
            Evidence(
                id=f"evidence-{index:03d}",
                project_id="project-budget",
                source_id=f"source-{index:03d}",
                source_content_checksum=f"checksum-{index:03d}",
                workflow_run_id=run_id,
                research_design_id=design_id,
                statement=f"Evidence {index}",
                source_excerpt=f"Excerpt {index}",
                created_at="2026-08-05T00:00:00+00:00",
                research_question_refs=(rq,),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key=f"dedup-{index:03d}",
            ),
        )
    return items


def _analysis_context(*, run_id: str = "run-budget") -> WorkflowContext:
    design = _six_rq_design()
    template = WorkflowTemplate(id="template-budget", name="Budget")
    brief = ResearchBrief(title="Budget", business_question="Assessment")
    template.research_design_snapshot = design
    template.research_brief_snapshot = brief
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template,
        run_id=run_id,
    )
    return WorkflowContext(
        project=ProjectFactory().create("Budget Project"),
        workflow_run=run,
        workflow_template=template,
    )


class BudgetExceptionPropagationTests(unittest.TestCase):
    def test_analysis_engine_propagates_budget_exhausted_unwrapped(self) -> None:
        mock = Mock()
        mock.generate.side_effect = BudgetExhaustedError(
            "llm_max_calls_per_run",
            stage="analysis",
        )
        engine = LlmAnalysisEngine(llm_client=mock)
        from application.ports.analysis_ports import AnalysisInput

        analysis_input = AnalysisInput(
            project_id="p",
            workflow_run_id="r",
            research_design_id="d",
            brief=ResearchBrief(title="t", business_question="q"),
            design=_six_rq_design(),
            evidence_batch=(),
        )
        with self.assertRaises(BudgetExhaustedError):
            engine.analyze_findings(analysis_input)
        with self.assertRaises(BudgetExhaustedError):
            engine.analyze_insights(analysis_input)
        self.assertNotIsInstance(
            BudgetExhaustedError("x", stage="analysis"),
            AnalysisConfigurationError,
        )

    def test_evidence_engine_propagates_budget_exhausted_unwrapped(self) -> None:
        from domain.sources.source import Source

        mock = Mock()
        mock.generate.side_effect = BudgetExhaustedError(
            "evidence_max_llm_calls",
            stage="evidence",
        )
        extractor = LlmEvidenceExtractor(llm_client=mock)
        from application.evidence.exceptions import EvidenceConfigurationError
        from application.evidence.run_scoped_provenance import RunScopedSourceContext

        from domain.planning.research_design import InformationNeed

        design = ResearchDesign(
            id="design-evidence",
            research_questions=(
                ResearchQuestion(
                    id="RQ1",
                    question="Q?",
                    objective_refs=("obj-1",),
                    priority=1,
                    rationale="",
                ),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="RQ1",
                    description="Need",
                ),
            ),
            source_strategy=("web",),
            analysis_plan=("analyze",),
            deliverable_plan=("report",),
            assumptions=(),
            limitations=(),
            language="en",
        )
        with self.assertRaises(BudgetExhaustedError):
            extractor.extract(
                source=Source(
                    id="s1",
                    project_id="p",
                    title="Title",
                    url="https://example.com",
                    canonical_url="https://example.com",
                    content_text="Sample text",
                    retrieval_status="success",
                    retrieved_at="2026-08-05T00:00:00+00:00",
                ),
                design=design,
                run_context=RunScopedSourceContext(
                    workflow_run_id="r",
                    research_design_id="d",
                    information_need_ids=("in-1",),
                    research_question_ids=("RQ1",),
                    query_ids=("sq-in-1",),
                ),
            )
        self.assertFalse(
            issubclass(BudgetExhaustedError, EvidenceConfigurationError),
        )

    def test_report_engine_propagates_budget_exhausted_unwrapped(self) -> None:
        from application.report.exceptions import ReportConfigurationError

        mock = Mock()
        mock.generate.side_effect = BudgetExhaustedError(
            "report_max_llm_calls",
            stage="report",
        )
        engine = LlmReportEngine(
            llm_client=mock,
            structured_output_max_attempts=1,
        )
        from application.ports.report_ports import ReportInput

        report_input = ReportInput(
            project_id="p",
            workflow_run_id="r",
            research_design_id="d",
            brief=ResearchBrief(title="t", business_question="q", language="en"),
            design=_six_rq_design(),
            findings=(),
            insights=(),
            evidence_by_id={},
            sources_by_id={},
            section_titles=("Summary",),
        )
        with self.assertRaises(BudgetExhaustedError):
            engine.generate_sections(report_input)
        self.assertFalse(
            issubclass(BudgetExhaustedError, ReportConfigurationError),
        )


class AnalysisFailFastTests(unittest.TestCase):
    def test_global_budget_exhausted_before_analysis_fails_on_first_batch(self) -> None:
        context = _analysis_context()
        run_id = context.workflow_run.id
        design = context.workflow_template.research_design_snapshot
        assert design is not None

        evidence_repo = InMemoryEvidenceRepository()
        for item in _evidence_for_batches(run_id=run_id, design_id=design.id):
            evidence_repo.create(item)

        mock = Mock()
        mock.generate.side_effect = BudgetExhaustedError(
            "llm_max_calls_per_run",
            stage="analysis",
        )
        budget = ExecutionBudget(
            llm_max_calls_per_run=100,
            analysis_max_llm_calls=14,
        )
        budget._total_llm_calls = 100
        budget._exhausted = True
        budget._exhaustion_reason = "llm_max_calls_per_run"
        budget._exhaustion_stage = "evidence"

        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        set_execution_stage("analysis")
        try:
            service = AnalysisService(
                analysis_engine=LlmAnalysisEngine(
                    llm_client=BudgetEnforcingLLMClient(mock),
                ),
                evidence_repository=evidence_repo,
                finding_repository=InMemoryFindingRepository(),
                insight_repository=InMemoryInsightRepository(),
                max_evidence_per_batch=2,
                max_chars_per_batch=12000,
            )
            with self.assertRaises(AnalysisError):
                service.analyze_for_context(context)
        finally:
            _current_budget.reset(token)

        self.assertEqual(mock.generate.call_count, 0)

    def test_analysis_stops_after_first_batch_on_budget_exhaustion(self) -> None:
        context = _analysis_context()
        run_id = context.workflow_run.id
        design = context.workflow_template.research_design_snapshot
        assert design is not None

        evidence_repo = InMemoryEvidenceRepository()
        for item in _evidence_for_batches(run_id=run_id, design_id=design.id):
            evidence_repo.create(item)

        mock = Mock()
        budget = ExecutionBudget(llm_max_calls_per_run=100, analysis_max_llm_calls=14)
        budget._total_llm_calls = 100
        budget._exhausted = True
        budget._exhaustion_reason = "llm_max_calls_per_run"
        budget._exhaustion_stage = "evidence"

        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        set_execution_stage("analysis")
        try:
            service = AnalysisService(
                analysis_engine=LlmAnalysisEngine(
                    llm_client=BudgetEnforcingLLMClient(mock),
                ),
                evidence_repository=evidence_repo,
                finding_repository=InMemoryFindingRepository(),
                insight_repository=InMemoryInsightRepository(),
                max_evidence_per_batch=2,
                max_chars_per_batch=12000,
            )
            with self.assertRaises(AnalysisError):
                service.analyze_for_context(context)
        finally:
            _current_budget.reset(token)

        self.assertEqual(mock.generate.call_count, 0)
        self.assertEqual(len(InMemoryFindingRepository().list_for_project("x")), 0)


class StageReservationTests(unittest.TestCase):
    def test_evidence_respects_downstream_reserve(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=100,
            evidence_max_llm_calls=100,
            analysis_max_llm_calls=14,
            report_max_llm_calls=20,
            review_max_llm_calls=7,
        )
        set_execution_stage("evidence")
        downstream_reserve = 14 + 20 + 7
        max_evidence_global = 100 - downstream_reserve

        for _ in range(max_evidence_global):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")

        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, "downstream_reserve_exhausted")

    def test_evidence_stage_cap_blocks_at_limit(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=100,
            evidence_max_llm_calls=3,
            analysis_max_llm_calls=14,
            report_max_llm_calls=20,
            review_max_llm_calls=7,
        )
        set_execution_stage("evidence")
        for _ in range(3):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")

        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, "evidence_max_llm_calls")


class RunUsageSummaryPersistenceTests(unittest.TestCase):
    def test_finalize_persists_exhaustion_stage(self) -> None:
        context = _analysis_context()
        budget = ensure_run_budget(context)
        budget.record_llm_call("planner")
        budget.record_llm_call("evidence")
        budget._exhausted = True
        budget._exhaustion_reason = "llm_max_calls_per_run"
        budget._exhaustion_stage = "evidence"

        summary = finalize_run_budget(context)
        assert summary is not None
        payload = summary.to_dict()
        self.assertTrue(payload["budget_exhausted"])
        self.assertEqual(payload["exhaustion_reason"], "llm_max_calls_per_run")
        self.assertEqual(payload["exhaustion_stage"], "evidence")
        self.assertEqual(payload["stages"]["evidence"]["llm_calls"], 1)
        self.assertEqual(payload["stages"]["planner"]["llm_calls"], 1)
        self.assertIn("run_usage_summary", context.shared_state)

    def test_workflow_persister_stores_usage_on_finalize(self) -> None:
        context = _analysis_context()
        budget = ensure_run_budget(context)
        budget._exhausted = True
        budget._exhaustion_reason = "evidence_max_llm_calls"
        budget._exhaustion_stage = "evidence"
        budget.record_llm_call("evidence")
        finalize_run_budget(context)

        persister = WorkflowRuntimePersister(
            workflow_service=Mock(),
            audit=Mock(),
            run_id=context.workflow_run.id,
        )
        persister.on_workflow_finalized(context, error=RuntimeError("failed"))
        usage = persister.task_results.get("_run_usage_summary")
        self.assertIsInstance(usage, dict)
        self.assertTrue(usage["budget_exhausted"])
        self.assertEqual(usage["exhaustion_stage"], "evidence")


class LiveShapedBudgetFitTests(unittest.TestCase):
    def test_seven_rq_batches_plus_insights_fit_analysis_cap(self) -> None:
        budget = ExecutionBudget(analysis_max_llm_calls=14)
        set_execution_stage("analysis")
        for _ in range(7):
            budget.assert_can_call("analysis")
            budget.record_llm_call("analysis")
        budget.assert_can_call("analysis")
        budget.record_llm_call("analysis")
        self.assertEqual(budget._stage_calls("analysis"), 8)

    def test_full_pipeline_stage_caps_sum_within_global(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=100,
            evidence_max_llm_calls=50,
            analysis_max_llm_calls=14,
            report_max_llm_calls=20,
            review_max_llm_calls=7,
        )
        total_cap = (
            budget.evidence_max_llm_calls
            + budget.analysis_max_llm_calls
            + budget.report_max_llm_calls
            + budget.review_max_llm_calls
        )
        self.assertLessEqual(total_cap, budget.llm_max_calls_per_run)


class WorkerSurvivalTests(unittest.TestCase):
    def test_workflow_engine_survives_budget_exhausted_task_failure(self) -> None:
        project = ProjectFactory().create("Worker Budget Project")
        template = WorkflowTemplate(id="tmpl-worker", name="Worker")
        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(template)
        workflow_run.project_id = project.id
        task = Task(
            id="task-analysis",
            definition_id="analyze",
            name="Analyze",
            executor_id="analysis",
            executor_type=ExecutorType.AGENT,
            status=TaskStatus.READY,
        )
        workflow_run.tasks = (task,)
        context = WorkflowContext(
            project=project,
            workflow_run=workflow_run,
            workflow_template=template,
        )

        from application.analysis.exceptions import AnalysisError

        class _Scheduler(TaskScheduler):
            def schedule(self, workflow_run):
                return SchedulingResult.empty()

            def find_ready_task(self, workflow_run):
                for item in workflow_run.tasks:
                    if item.status == TaskStatus.READY:
                        return item
                return None

        class _FailingAnalysisExecutor:
            def run(self, ctx: WorkflowContext) -> WorkflowContext:
                set_execution_stage("analysis")
                raise AnalysisError("budget exhausted during analysis")

        engine = WorkflowEngine(
            scheduler=_Scheduler(),
            task_executor=TaskExecutor(
                _Resolver(_FailingAnalysisExecutor()),
                TaskLifecycleManager(),
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )

        ensure_run_budget(context)
        with self.assertRaises(AnalysisError):
            engine.run(context)

        summary = context.execution_metadata.get(RUN_USAGE_SUMMARY_KEY)
        self.assertIsInstance(summary, RunUsageSummary)
        self.assertEqual(summary.total_llm_calls, 0)


class _Resolver:
    def __init__(self, executor) -> None:
        self._executor = executor

    def resolve(self, task: Task):
        return self._executor
