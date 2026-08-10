"""Production wiring tests for per-run ExecutionBudget enforcement."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task import Task
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_template import WorkflowTemplate

from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    EXECUTION_BUDGET_KEY,
    RUN_USAGE_SUMMARY_KEY,
    ensure_run_budget,
    finalize_run_budget,
    set_execution_stage,
)
from application.report.exceptions import ReportError
from application.review.exceptions import ReviewError
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.scheduling.scheduling_result import SchedulingResult
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.telemetry.run_usage_summary import RunUsageSummary
from application.workflow_engine import WorkflowEngine
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.review.llm_review_engine import LlmReviewEngine
from runtime.workflow_context import WorkflowContext

from tests.infrastructure.review.test_llm_review_engine import _semantic_input


class _CountingExecutor:
    def __init__(self, *, client: BudgetEnforcingLLMClient, stage: str) -> None:
        self._client = client
        self._stage = stage
        self.calls = 0

    def run(self, context: WorkflowContext) -> WorkflowContext:
        set_execution_stage(self._stage)
        from domain.ai.prompt import Prompt

        self._client.generate(Prompt(system="s", user="u"))
        self.calls += 1
        return context


class _Resolver:
    def __init__(self, executor: _CountingExecutor) -> None:
        self._executor = executor

    def resolve(self, task: Task) -> _CountingExecutor:
        return self._executor


class BudgetEnforcingLLMClientTests(unittest.TestCase):
    def test_records_calls_against_active_budget(self) -> None:
        budget = ExecutionBudget(report_max_llm_calls=5, llm_max_calls_per_run=10)
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok", output_tokens=12)
        client = BudgetEnforcingLLMClient(mock)
        set_execution_stage("report")
        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        try:
            from domain.ai.prompt import Prompt

            client.generate(Prompt(system="s", user="u"))
        finally:
            _current_budget.reset(token)

        self.assertEqual(mock.generate.call_count, 1)
        self.assertEqual(budget.summary()["stages"]["report"]["llm_calls"], 1)
        self.assertEqual(budget.summary()["total_llm_calls"], 1)

    def test_report_stage_budget_blocks_extra_calls(self) -> None:
        budget = ExecutionBudget(report_max_llm_calls=2, llm_max_calls_per_run=100)
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok")
        client = BudgetEnforcingLLMClient(mock)
        set_execution_stage("report")
        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        try:
            from domain.ai.prompt import Prompt

            prompt = Prompt(system="s", user="u")
            client.generate(prompt)
            client.generate(prompt)
            with self.assertRaises(BudgetExhaustedError):
                client.generate(prompt)
        finally:
            _current_budget.reset(token)

        self.assertEqual(mock.generate.call_count, 2)

    def test_review_stage_budget_blocks_at_seven(self) -> None:
        budget = ExecutionBudget(review_max_llm_calls=7, llm_max_calls_per_run=100)
        mock = Mock()
        mock.generate.return_value = LLMResponse(
            content=json.dumps({"issues": []}),
        )
        engine = LlmReviewEngine(
            llm_client=BudgetEnforcingLLMClient(mock),
            max_review_calls=7,
            structured_output_max_attempts=1,
        )
        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        set_execution_stage("review")
        try:
            review_input = _semantic_input(section_content="Supported claim text.")
            for _ in range(7):
                engine.review_report(review_input)
            with self.assertRaises(BudgetExhaustedError):
                engine.review_report(
                    _semantic_input(section_content="Another claim."),
                )
        finally:
            _current_budget.reset(token)

        self.assertGreaterEqual(mock.generate.call_count, 7)

    def test_global_run_budget_blocks_at_limit(self) -> None:
        budget = ExecutionBudget(llm_max_calls_per_run=3)
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok")
        client = BudgetEnforcingLLMClient(mock)
        set_execution_stage("analysis")
        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        try:
            from domain.ai.prompt import Prompt

            prompt = Prompt(system="s", user="u")
            for _ in range(3):
                client.generate(prompt)
            with self.assertRaises(BudgetExhaustedError):
                client.generate(prompt)
        finally:
            _current_budget.reset(token)

    def test_retries_are_recorded(self) -> None:
        budget = ExecutionBudget(llm_max_calls_per_run=10)
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok")
        client = BudgetEnforcingLLMClient(mock)
        set_execution_stage("report")
        from application.execution.execution_budget_context import _current_budget
        from application.execution.execution_budget_retry import mark_llm_call_as_retry

        token = _current_budget.set(budget)
        try:
            from domain.ai.prompt import Prompt

            prompt = Prompt(system="s", user="u")
            client.generate(prompt)
            mark_llm_call_as_retry()
            client.generate(prompt)
        finally:
            _current_budget.reset(token)

        self.assertEqual(budget.summary()["stages"]["report"]["retries"], 1)


class WorkflowBudgetLifecycleTests(unittest.TestCase):
    def _workflow_context(self) -> WorkflowContext:
        project = ProjectFactory().create("Budget Project")
        template = WorkflowTemplate(id="template-budget", name="Budget Template")
        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(template)
        workflow_run.project_id = project.id
        task = Task(
            id="task-report",
            definition_id="write-report",
            name="Write Report",
            executor_id="report",
            executor_type=ExecutorType.AGENT,
            status=TaskStatus.READY,
        )
        workflow_run.tasks = (task,)
        return WorkflowContext(
            project=project,
            workflow_run=workflow_run,
            workflow_template=template,
        )

    def test_finalize_run_usage_summary_reflects_actual_calls(self) -> None:
        context = self._workflow_context()
        budget = ensure_run_budget(context)
        budget.report_max_llm_calls = 20
        set_execution_stage("report")
        budget.record_llm_call("report", output_tokens=50)
        budget.record_llm_call("report", output_tokens=25, retry=True)

        summary = finalize_run_budget(context)
        assert summary is not None
        payload = summary.to_dict()
        self.assertEqual(payload["total_llm_calls"], 2)
        self.assertEqual(payload["stages"]["report"]["llm_calls"], 2)
        self.assertEqual(payload["stages"]["report"]["retries"], 1)
        stored = context.execution_metadata[RUN_USAGE_SUMMARY_KEY]
        self.assertIsInstance(stored, RunUsageSummary)
        self.assertEqual(stored.total_llm_calls, 2)

    def test_workflow_engine_finalizes_budget_even_on_task_failure(self) -> None:
        context = self._workflow_context()
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok")
        client = BudgetEnforcingLLMClient(mock)
        executor = _CountingExecutor(client=client, stage="report")

        class _FailingScheduler(TaskScheduler):
            def schedule(self, workflow_run):
                return SchedulingResult.empty()

            def find_ready_task(self, workflow_run):
                for task in workflow_run.tasks:
                    if task.status == TaskStatus.READY:
                        return task
                return None

        engine = WorkflowEngine(
            scheduler=_FailingScheduler(),
            task_executor=TaskExecutor(_Resolver(executor), TaskLifecycleManager()),
            completion_policy=WorkflowCompletionPolicy(),
        )

        class _BoomExecutor(_CountingExecutor):
            def run(self, context: WorkflowContext) -> WorkflowContext:
                set_execution_stage("report")
                super().run(context)
                raise ReportError("simulated report failure")

        engine._task_executor = TaskExecutor(
            _Resolver(_BoomExecutor(client=client, stage="report")),
            TaskLifecycleManager(),
        )

        with self.assertRaises(ReportError):
            engine.run(context)

        summary = context.execution_metadata.get(RUN_USAGE_SUMMARY_KEY)
        self.assertIsInstance(summary, RunUsageSummary)
        self.assertEqual(summary.total_llm_calls, 1)
        self.assertFalse(summary.budget_exhausted)


class BudgetExhaustionBehaviorTests(unittest.TestCase):
    def test_review_budget_exhaustion_raises_without_persisting_retry_review(self) -> None:
        from application.review.review_service import ReviewService
        from application.report.report_service import ReportService
        from domain.reports.report import Report
        from domain.reports.report_section import ReportSection
        from infrastructure.persistence.memory.in_memory_artifact_repository import (
            InMemoryArtifactRepository,
        )
        from infrastructure.persistence.memory.in_memory_finding_repository import (
            InMemoryFindingRepository,
        )
        from infrastructure.persistence.memory.in_memory_evidence_repository import (
            InMemoryEvidenceRepository,
        )
        from infrastructure.persistence.memory.in_memory_insight_repository import (
            InMemoryInsightRepository,
        )
        from infrastructure.persistence.memory.in_memory_report_repository import (
            InMemoryReportRepository,
        )
        from infrastructure.persistence.memory.in_memory_review_repository import (
            InMemoryReviewRepository,
        )
        from infrastructure.report.deterministic_report_engine import (
            DeterministicReportEngine,
        )

        project = ProjectFactory().create("Review Budget Project")
        template = WorkflowTemplate(id="tmpl", name="T")
        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(template)
        workflow_run.project_id = project.id
        from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
        from tests.fixtures.research_brief import sample_research_brief

        brief = sample_research_brief()
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(
                    id="RQ1",
                    question="What is the market?",
                    objective_refs=("obj-1",),
                    priority=1,
                    rationale="Primary",
                ),
            ),
            information_needs=(
                InformationNeed(
                    id="in-a",
                    research_question_id="RQ1",
                    description="Market data",
                ),
            ),
            source_strategy=("web",),
            analysis_plan=("compare",),
            deliverable_plan=("summary",),
            assumptions=(),
            limitations=("Sample",),
            language="en",
        )
        template.research_brief_snapshot = brief
        template.research_design_snapshot = design
        context = WorkflowContext(
            project=project,
            workflow_run=workflow_run,
            workflow_template=template,
        )

        finding_repo = InMemoryFindingRepository()
        insight_repo = InMemoryInsightRepository()
        report_repo = InMemoryReportRepository()
        artifact_repo = InMemoryArtifactRepository()
        review_repo = InMemoryReviewRepository()

        report_service = ReportService(
            report_engine=DeterministicReportEngine(),
            finding_repository=finding_repo,
            insight_repository=insight_repo,
            evidence_repository=Mock(),
            source_repository=Mock(),
            report_repository=report_repo,
            artifact_repository=artifact_repo,
            max_findings_per_batch=10,
            max_chars_per_batch=12000,
        )

        mock = Mock()
        mock.generate.side_effect = BudgetExhaustedError(
            "review_max_llm_calls",
            stage="review",
        )
        review_engine = LlmReviewEngine(
            llm_client=BudgetEnforcingLLMClient(mock),
            max_review_calls=7,
            structured_output_max_attempts=1,
        )
        review_service = ReviewService(
            semantic_review_engine=review_engine,
            finding_repository=finding_repo,
            insight_repository=insight_repo,
            evidence_repository=InMemoryEvidenceRepository(),
            report_repository=report_repo,
            artifact_repository=artifact_repo,
            review_repository=review_repo,
            report_service=report_service,
            max_revision_attempts=2,
        )

        now = "2026-01-01T00:00:00+00:00"
        report_repo.create(
            Report(
                id="report-1",
                project_id=project.id,
                workflow_run_id=workflow_run.id,
                research_design_id="design-1",
                title="Draft",
                language="en",
                sections=(
                    ReportSection(
                        id="section-1",
                        title="Section",
                        content="Supported content.",
                        finding_refs=("finding-1",),
                        insight_refs=(),
                        evidence_refs=("evidence-1",),
                        citation_ids=("S1",),
                        research_question_refs=("RQ1",),
                    ),
                ),
                executive_summary="Summary",
                limitations=(),
                created_at=now,
                generation_method="deterministic",
                finding_refs=("finding-1",),
                insight_refs=(),
                evidence_refs=("evidence-1",),
                citation_registry={
                    "S1": {
                        "citation_id": "S1",
                        "source_id": "source-1",
                        "title": "Source",
                        "canonical_url": "https://example.com",
                        "published_at": None,
                        "retrieved_at": now,
                        "source_type": "web",
                    },
                },
                deduplication_key="dedup-report-1",
            ),
        )

        budget = ExecutionBudget(review_max_llm_calls=0, llm_max_calls_per_run=100)
        context.execution_metadata[EXECUTION_BUDGET_KEY] = budget
        from application.execution.execution_budget_context import _current_budget

        token = _current_budget.set(budget)
        set_execution_stage("review")
        try:
            with self.assertRaises(ReviewError):
                review_service.review_for_context(context)
        finally:
            _current_budget.reset(token)

        self.assertEqual(len(review_repo.list_for_project(project.id)), 0)
        self.assertEqual(mock.generate.call_count, 0)
