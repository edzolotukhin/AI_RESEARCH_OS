"""P1-18.1 offline acceptance for ResearchRunResult read projection."""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import ArtifactRecord
from application.query.research_run_result import (
    ResearchRunOutcome,
    ResearchRunResultProjectionError,
)
from application.query.research_run_result_query_service import (
    ResearchRunResultQueryService,
)
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.task_status import TaskStatus
from infrastructure.persistence.memory.in_memory_artifact_repository import (
    InMemoryArtifactRepository,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
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
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _terminal_complete(run) -> None:
    run.ready()
    run.start()
    run.complete()


def _terminal_fail(run) -> None:
    run.ready()
    run.start()
    run.fail()


def _readiness_snapshot(
    *,
    task_id: str,
    ready_for_analysis: bool,
    research_outcome: str,
    termination_reason: str = "",
    blocking_needs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "definition_id": "task-assess-research-readiness",
        "shared_state": {
            "research_readiness": {
                "ready_for_analysis": ready_for_analysis,
                "research_outcome": research_outcome,
                "termination_reason": termination_reason,
                "blocking_information_need_ids": list(blocking_needs or []),
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
                "research_loop_count": 1,
                "research_loop_history": [],
            }
        },
    }


class _ReadOnlyGuard:
    """Proxy that forbids create/save/update/delete while allowing reads."""

    _FORBIDDEN = ("create", "save", "update", "delete", "remove", "append")

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            lowered = name.lower()
            if any(token in lowered for token in self._FORBIDDEN):
                raise AssertionError(f"Write method invoked on read path: {name}")
            return attr(*args, **kwargs)

        return _wrapped


class ResearchRunResultQueryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_repo = InMemoryWorkflowRunRepository()
        self.source_repo = InMemorySourceRepository()
        self.evidence_repo = InMemoryEvidenceRepository()
        self.finding_repo = InMemoryFindingRepository()
        self.insight_repo = InMemoryInsightRepository()
        self.report_repo = InMemoryReportRepository()
        self.review_repo = InMemoryReviewRepository()
        self.artifact_repo = InMemoryArtifactRepository()
        self.service = ResearchRunResultQueryService(
            workflow_run_repository=self.run_repo,
            source_repository=self.source_repo,
            evidence_repository=self.evidence_repo,
            finding_repository=self.finding_repo,
            insight_repository=self.insight_repo,
            report_repository=self.report_repo,
            review_repository=self.review_repo,
            artifact_repository=self.artifact_repo,
        )

    def _pipeline_tasks(
        self,
        *,
        readiness_status: TaskStatus = TaskStatus.COMPLETED,
        analyze_status: TaskStatus = TaskStatus.COMPLETED,
        report_status: TaskStatus = TaskStatus.COMPLETED,
        review_status: TaskStatus = TaskStatus.COMPLETED,
        readiness_task_id: str = "task-ready-1",
    ):
        collect = make_task(
            "task-collect-evidence",
            status=TaskStatus.COMPLETED,
            executor_id="search",
            task_id="task-collect-1",
        )
        extract = make_task(
            "task-extract-evidence",
            depends_on=[collect.definition_id],
            status=TaskStatus.COMPLETED,
            executor_id="evidence",
            task_id="task-extract-1",
        )
        readiness = make_task(
            "task-assess-research-readiness",
            depends_on=[extract.definition_id],
            status=readiness_status,
            executor_id="research_quality",
            task_id=readiness_task_id,
        )
        analyze = make_task(
            "task-analyze",
            depends_on=[readiness.definition_id],
            status=analyze_status,
            executor_id="analysis",
            task_id="task-analyze-1",
        )
        write = make_task(
            "task-write-report",
            depends_on=[analyze.definition_id],
            status=report_status,
            executor_id="report",
            task_id="task-write-1",
        )
        review = make_task(
            "task-review-report",
            depends_on=[write.definition_id],
            status=review_status,
            executor_id="review",
            task_id="task-review-1",
        )
        return collect, extract, readiness, analyze, write, review

    def _seed_run(
        self,
        *,
        run_id: str,
        project_id: str,
        terminal: Callable[[Any], None],
        tasks,
        task_results: dict[str, Any],
    ):
        run = make_workflow_run(*tasks, run_id=run_id)
        run.project_id = project_id
        terminal(run)
        self.run_repo.create(run, project_id=project_id)
        self.run_repo.save(run, expected_version=0, task_results=task_results)
        return run

    def _add_source(
        self,
        *,
        source_id: str,
        project_id: str,
        run_id: str,
        status: RetrievalStatus = RetrievalStatus.ACQUIRED,
        content_text: str = "SOURCE_BODY_SHOULD_NOT_APPEAR",
    ) -> Source:
        source = Source(
            id=source_id,
            project_id=project_id,
            url=f"https://example.com/{source_id}",
            canonical_url=f"https://example.com/{source_id}",
            title=source_id,
            retrieved_at="2026-08-11T00:00:00+00:00",
            workflow_run_refs=(run_id,),
            research_design_refs=("design-1",),
            retrieval_status=status,
            content_text=content_text,
        )
        self.source_repo.create(source)
        return source

    def _add_evidence(
        self,
        *,
        evidence_id: str,
        source_id: str,
        project_id: str,
        run_id: str,
        statement: str = "Evidence statement",
    ) -> Evidence:
        evidence = Evidence(
            id=evidence_id,
            project_id=project_id,
            source_id=source_id,
            source_content_checksum="checksum",
            workflow_run_id=run_id,
            research_design_id="design-1",
            statement=statement,
            source_excerpt="EXCERPT_SHOULD_NOT_DUMP",
            created_at="2026-08-11T00:00:00+00:00",
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            deduplication_key=f"dedup-{evidence_id}",
        )
        self.evidence_repo.create(evidence)
        return evidence

    def _add_finding(
        self,
        *,
        finding_id: str,
        evidence_ids: tuple[str, ...],
        project_id: str,
        run_id: str,
        statement: str = "Finding statement",
    ) -> Finding:
        finding = Finding(
            id=finding_id,
            project_id=project_id,
            workflow_run_id=run_id,
            research_design_id="design-1",
            statement=statement,
            rationale="rationale",
            evidence_refs=evidence_ids,
            created_at="2026-08-11T00:00:00+00:00",
            finding_type=FindingType.SYNTHESIS,
            deduplication_key=f"dedup-{finding_id}",
        )
        self.finding_repo.create(finding)
        return finding

    def _add_insight(
        self,
        *,
        insight_id: str,
        finding_ids: tuple[str, ...],
        project_id: str,
        run_id: str,
    ) -> Insight:
        insight = Insight(
            id=insight_id,
            project_id=project_id,
            workflow_run_id=run_id,
            research_design_id="design-1",
            statement="Insight statement",
            implication="implication",
            finding_refs=finding_ids,
            created_at="2026-08-11T00:00:00+00:00",
            deduplication_key=f"dedup-{insight_id}",
        )
        self.insight_repo.create(insight)
        return insight

    def _add_report(
        self,
        *,
        report_id: str,
        project_id: str,
        run_id: str,
        revision_number: int,
        previous_report_id: str | None = None,
        finding_refs: tuple[str, ...] = (),
        insight_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
        citation_registry: dict[str, dict[str, Any]] | None = None,
    ) -> Report:
        report = Report(
            id=report_id,
            project_id=project_id,
            workflow_run_id=run_id,
            research_design_id="design-1",
            title=f"Report {revision_number}",
            language="en",
            sections=(),
            executive_summary="Executive summary",
            limitations=limitations,
            created_at="2026-08-11T00:00:00+00:00",
            generation_method="test",
            finding_refs=finding_refs,
            insight_refs=insight_refs,
            evidence_refs=evidence_refs,
            citation_registry=citation_registry or {},
            deduplication_key=f"report-rev-{revision_number}",
            revision_number=revision_number,
            previous_report_id=previous_report_id,
        )
        self.report_repo.create(report)
        return report

    def _add_review(
        self,
        *,
        review_id: str,
        report_id: str,
        project_id: str,
        run_id: str,
        attempt: int,
        verdict: ReviewVerdict,
        artifact_id: str | None = None,
        created_at: str = "2026-08-11T00:00:00+00:00",
    ) -> ReviewResult:
        issues = ()
        if verdict != ReviewVerdict.APPROVE:
            issues = (
                ReviewIssue(
                    id=f"issue-{review_id}",
                    issue_type=ReviewIssueType.MISSING_CITATION,
                    severity=ReviewIssueSeverity.MAJOR,
                    message="citation missing",
                ),
            )
        review = ReviewResult(
            id=review_id,
            project_id=project_id,
            workflow_run_id=run_id,
            research_design_id="design-1",
            report_id=report_id,
            review_attempt=attempt,
            verdict=verdict,
            quality_dimensions=(),
            issues=issues,
            summary=f"Review {attempt}",
            review_method="test",
            created_at=created_at,
            deduplication_key=f"review-{report_id}-{attempt}",
            artifact_id=artifact_id,
        )
        self.review_repo.create(review)
        return review

    def _add_artifact(
        self,
        *,
        artifact_id: str,
        project_id: str,
        run_id: str,
        report_id: str,
        status: str,
        dedup_suffix: str,
    ) -> ArtifactRecord:
        artifact = ArtifactRecord(
            id=artifact_id,
            project_id=project_id,
            artifact_type="report",
            title="Artifact",
            content="artifact-content",
            run_id=run_id,
            status=status,
            deduplication_key=f"artifact-{dedup_suffix}",
            report_id=report_id,
        )
        self.artifact_repo.create(artifact)
        return artifact

    def test_case_01_approved_p1_08_live2_shape(self) -> None:
        run_id = "d6316ebd-fd40-43f8-9ff7-6eab9fd20470"
        project_id = "dfffd061-87c2-4e56-9151-272b00c98e21"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
                "_run_usage_summary": {
                    "total_llm_calls": 12,
                    "estimated_cost_usd": 0.42,
                    "budget_exhausted": False,
                    "stages": {"analysis": {"llm_calls": 3}},
                },
            },
        )
        self._add_source(source_id="src-1", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev-1",
            source_id="src-1",
            project_id=project_id,
            run_id=run_id,
        )
        self._add_finding(
            finding_id="f-1",
            evidence_ids=("ev-1",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_insight(
            insight_id="i-1",
            finding_ids=("f-1",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_report(
            report_id="rep-1",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            finding_refs=("f-1",),
            insight_refs=("i-1",),
            evidence_refs=("ev-1",),
            citation_registry={"c1": {"source_id": "src-1"}},
        )
        self._add_artifact(
            artifact_id="art-1",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-1",
            status="approved",
            dedup_suffix="1",
        )
        self._add_review(
            review_id="rev-1",
            report_id="rep-1",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.APPROVE,
            artifact_id="art-1",
        )

        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.APPROVED)
        self.assertEqual(result.workflow_status, "completed")
        self.assertEqual(result.artifact_status.approved_artifact_id, "art-1")
        self.assertEqual(result.latest_review.verdict, "approve")
        self.assertNotEqual(result.outcome.value, result.workflow_status)

    def test_case_02_not_ready_p1_16_shape(self) -> None:
        run_id = "45a75881-73e2-444d-a50d-8d049b4f192b"
        project_id = "c3e80445-not-ready-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="downstream_reserve_exhausted",
                    blocking_needs=["IN1"],
                ),
                "_run_usage_summary": {
                    "total_llm_calls": 59,
                    "budget_exhausted": True,
                    "exhaustion_reason": "downstream_reserve_exhausted",
                    "stages": {},
                },
            },
        )
        self._add_source(source_id="src-nr", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev-nr",
            source_id="src-nr",
            project_id=project_id,
            run_id=run_id,
        )

        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.NOT_READY)
        self.assertEqual(result.workflow_status, "completed")
        self.assertNotEqual(result.outcome, ResearchRunOutcome.APPROVED)
        self.assertEqual(result.termination_reason, "downstream_reserve_exhausted")
        self.assertEqual(result.finding_summary.count, 0)
        self.assertIsNone(result.latest_report)
        self.assertIsNone(result.artifact_status.approved_artifact_id)

    def test_case_03_execution_failed_p1_12_shape(self) -> None:
        run_id = "p1-12-failed-run"
        project_id = "p1-12-project"
        tasks = self._pipeline_tasks(
            readiness_status=TaskStatus.FAILED,
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_fail,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="",
                ),
            },
        )

        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.EXECUTION_FAILED)
        self.assertEqual(result.workflow_status, "failed")
        self.assertNotEqual(result.outcome, ResearchRunOutcome.NOT_READY)

    def test_case_04_quality_rejected_p1_09_1_revise_exhaustion(self) -> None:
        run_id = "3b60b098-0343-4be2-afde-b33811ba6ea7"
        project_id = "p1-09-project"
        tasks = self._pipeline_tasks(review_status=TaskStatus.FAILED)
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_fail,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_report(
            report_id="rep-r1",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
        )
        self._add_report(
            report_id="rep-r2",
            project_id=project_id,
            run_id=run_id,
            revision_number=2,
            previous_report_id="rep-r1",
        )
        self._add_artifact(
            artifact_id="art-rej",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-r2",
            status="rejected",
            dedup_suffix="rej",
        )
        self._add_review(
            review_id="rev-1",
            report_id="rep-r1",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REVISE,
            created_at="2026-08-11T01:00:00+00:00",
        )
        self._add_review(
            review_id="rev-2",
            report_id="rep-r2",
            project_id=project_id,
            run_id=run_id,
            attempt=2,
            verdict=ReviewVerdict.REVISE,
            created_at="2026-08-11T02:00:00+00:00",
        )

        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.QUALITY_REJECTED)
        self.assertEqual(result.workflow_status, "failed")
        self.assertNotEqual(result.outcome, ResearchRunOutcome.EXECUTION_FAILED)
        self.assertEqual(result.latest_report.id, "rep-r2")
        self.assertEqual(result.latest_review.review_attempt, 2)
        self.assertEqual(result.latest_review.verdict, "revise")

    def test_case_05_latest_report_revision_selected(self) -> None:
        run_id = "rev-report-run"
        project_id = "rev-report-project"
        tasks = self._pipeline_tasks(review_status=TaskStatus.FAILED)
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_fail,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_report(
            report_id="old",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
        )
        self._add_report(
            report_id="new",
            project_id=project_id,
            run_id=run_id,
            revision_number=3,
            previous_report_id="mid",
        )
        self._add_report(
            report_id="mid",
            project_id=project_id,
            run_id=run_id,
            revision_number=2,
            previous_report_id="old",
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="new",
            status="rejected",
            dedup_suffix="x",
        )
        self._add_review(
            review_id="r",
            report_id="new",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REJECT,
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.latest_report.id, "new")
        self.assertEqual(result.latest_report.revision_number, 3)

    def test_case_06_latest_review_attempt_selected(self) -> None:
        run_id = "rev-review-run"
        project_id = "rev-review-project"
        tasks = self._pipeline_tasks(review_status=TaskStatus.FAILED)
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_fail,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_report(
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="rep",
            status="rejected",
            dedup_suffix="y",
        )
        self._add_review(
            review_id="early",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REVISE,
            created_at="2026-08-11T01:00:00+00:00",
        )
        self._add_review(
            review_id="late",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=4,
            verdict=ReviewVerdict.REJECT,
            created_at="2026-08-11T04:00:00+00:00",
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.latest_review.id, "late")
        self.assertEqual(result.latest_review.review_attempt, 4)

    def test_case_07_approved_wins_over_stale_rejected(self) -> None:
        run_id = "approved-stale-run"
        project_id = "approved-stale-project"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_report(
            report_id="rep-old",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
        )
        self._add_report(
            report_id="rep-new",
            project_id=project_id,
            run_id=run_id,
            revision_number=2,
            previous_report_id="rep-old",
        )
        self._add_artifact(
            artifact_id="art-old",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-old",
            status="rejected",
            dedup_suffix="old",
        )
        self._add_artifact(
            artifact_id="art-new",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-new",
            status="approved",
            dedup_suffix="new",
        )
        self._add_review(
            review_id="rev-old",
            report_id="rep-old",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REVISE,
            created_at="2026-08-11T01:00:00+00:00",
        )
        self._add_review(
            review_id="rev-new",
            report_id="rep-new",
            project_id=project_id,
            run_id=run_id,
            attempt=2,
            verdict=ReviewVerdict.APPROVE,
            created_at="2026-08-11T02:00:00+00:00",
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.APPROVED)
        self.assertEqual(result.artifact_status.approved_artifact_id, "art-new")
        self.assertEqual(result.latest_report.id, "rep-new")

    def test_case_08_not_ready_with_substantial_evidence(self) -> None:
        run_id = "not-ready-evidence-run"
        project_id = "not-ready-evidence-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="downstream_reserve_exhausted",
                ),
            },
        )
        self._add_source(source_id="s0", project_id=project_id, run_id=run_id)
        for index in range(25):
            self._add_evidence(
                evidence_id=f"ev-{index:03d}",
                source_id="s0",
                project_id=project_id,
                run_id=run_id,
            )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.NOT_READY)
        self.assertEqual(result.evidence_summary.count, 25)

    def test_case_09_contradictory_state_fail_closed(self) -> None:
        run_id = "contradiction-run"
        project_id = "contradiction-project"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_report(
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="rep",
            status="approved",
            dedup_suffix="bad",
        )
        self._add_review(
            review_id="rev",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REJECT,
        )
        with self.assertRaises(ResearchRunResultProjectionError):
            self.service.get_for_run(run_id)

    def test_case_10_provenance_chain(self) -> None:
        run_id = "prov-run"
        project_id = "prov-project"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_source(source_id="src", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev",
            source_id="src",
            project_id=project_id,
            run_id=run_id,
        )
        self._add_finding(
            finding_id="f",
            evidence_ids=("ev",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_insight(
            insight_id="i",
            finding_ids=("f",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_report(
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            finding_refs=("f",),
            insight_refs=("i",),
            evidence_refs=("ev",),
            citation_registry={"c1": {"source_id": "src"}},
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="rep",
            status="approved",
            dedup_suffix="p",
        )
        self._add_review(
            review_id="rev",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.APPROVE,
            artifact_id="art",
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.provenance_summary.source_ids, ("src",))
        self.assertEqual(result.provenance_summary.evidence_ids, ("ev",))
        self.assertEqual(result.provenance_summary.finding_ids, ("f",))
        self.assertEqual(result.provenance_summary.insight_ids, ("i",))
        self.assertTrue(result.provenance_summary.links)
        self.assertEqual(result.provenance_summary.unresolved_refs, ())

    def test_case_11_foreign_refs_not_valid_provenance(self) -> None:
        run_id = "foreign-run"
        other_run = "other-run"
        project_id = "foreign-project"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
            },
        )
        self._add_source(source_id="src-local", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev-local",
            source_id="src-local",
            project_id=project_id,
            run_id=run_id,
        )
        # Cross-run evidence/finding exist in project but wrong run.
        self._add_source(source_id="src-x", project_id=project_id, run_id=other_run)
        self._add_evidence(
            evidence_id="ev-x",
            source_id="src-x",
            project_id=project_id,
            run_id=other_run,
        )
        self._add_finding(
            finding_id="f-x",
            evidence_ids=("ev-x",),
            project_id=project_id,
            run_id=other_run,
        )
        self._add_report(
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            finding_refs=("f-x", "missing-f"),
            evidence_refs=("ev-x",),
            citation_registry={"c1": {"source_id": "src-x"}},
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="rep",
            status="approved",
            dedup_suffix="fx",
        )
        self._add_review(
            review_id="rev",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.APPROVE,
            artifact_id="art",
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.provenance_summary.finding_ids, ())
        self.assertEqual(result.provenance_summary.evidence_ids, ())
        self.assertNotIn("src-x", result.provenance_summary.source_ids)
        unresolved_ids = {item["id"] for item in result.provenance_summary.unresolved_refs}
        self.assertIn("f-x", unresolved_ids)
        self.assertIn("ev-x", unresolved_ids)
        self.assertIn("src-x", unresolved_ids)
        self.assertIn("missing-f", unresolved_ids)

    def test_case_12_empty_downstream_on_not_ready(self) -> None:
        run_id = "empty-downstream-run"
        project_id = "empty-downstream-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="sufficiency_budget_exhausted",
                ),
            },
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.NOT_READY)
        self.assertEqual(result.source_summary.count, 0)
        self.assertEqual(result.evidence_summary.count, 0)
        self.assertEqual(result.finding_summary.count, 0)
        self.assertEqual(result.insight_summary.count, 0)

    def test_case_13_budget_usage_absent_partial(self) -> None:
        run_id = "budget-absent-run"
        project_id = "budget-absent-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="downstream_reserve_exhausted",
                ),
            },
        )
        result = self.service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.NOT_READY)
        self.assertFalse(result.budget_usage.available)
        self.assertTrue(result.budget_usage.partial)

    def test_case_14_deterministic_projection(self) -> None:
        run_id = "deterministic-run"
        project_id = "deterministic-project"
        tasks = self._pipeline_tasks()
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=True,
                    research_outcome="ready_for_analysis",
                ),
                "_run_usage_summary": {"total_llm_calls": 2, "stages": {}},
            },
        )
        self._add_source(source_id="src-b", project_id=project_id, run_id=run_id)
        self._add_source(source_id="src-a", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev-b",
            source_id="src-a",
            project_id=project_id,
            run_id=run_id,
        )
        self._add_evidence(
            evidence_id="ev-a",
            source_id="src-b",
            project_id=project_id,
            run_id=run_id,
        )
        self._add_finding(
            finding_id="f-a",
            evidence_ids=("ev-a",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_report(
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            finding_refs=("f-a",),
            evidence_refs=("ev-a", "ev-b"),
        )
        self._add_artifact(
            artifact_id="art",
            project_id=project_id,
            run_id=run_id,
            report_id="rep",
            status="approved",
            dedup_suffix="d",
        )
        self._add_review(
            review_id="rev",
            report_id="rep",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.APPROVE,
            artifact_id="art",
        )
        first = self.service.get_for_run(run_id).to_dict()
        second = self.service.get_for_run(run_id).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )
        self.assertEqual(first["source_summary"]["ids"], ["src-a", "src-b"])
        self.assertEqual(first["evidence_summary"]["ids"], ["ev-a", "ev-b"])

    def test_case_15_query_service_is_read_only(self) -> None:
        run_id = "readonly-run"
        project_id = "readonly-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="downstream_reserve_exhausted",
                ),
            },
        )
        guarded = {
            "workflow": _ReadOnlyGuard(self.run_repo),
            "source": _ReadOnlyGuard(self.source_repo),
            "evidence": _ReadOnlyGuard(self.evidence_repo),
            "finding": _ReadOnlyGuard(self.finding_repo),
            "insight": _ReadOnlyGuard(self.insight_repo),
            "report": _ReadOnlyGuard(self.report_repo),
            "review": _ReadOnlyGuard(self.review_repo),
            "artifact": _ReadOnlyGuard(self.artifact_repo),
        }
        service = ResearchRunResultQueryService(
            workflow_run_repository=guarded["workflow"],
            source_repository=guarded["source"],
            evidence_repository=guarded["evidence"],
            finding_repository=guarded["finding"],
            insight_repository=guarded["insight"],
            report_repository=guarded["report"],
            review_repository=guarded["review"],
            artifact_repository=guarded["artifact"],
        )
        result = service.get_for_run(run_id)
        self.assertEqual(result.outcome, ResearchRunOutcome.NOT_READY)
        for name, guard in guarded.items():
            for call in guard.calls:
                self.assertFalse(
                    any(token in call.lower() for token in _ReadOnlyGuard._FORBIDDEN),
                    msg=f"{name}.{call}",
                )

    def test_bounded_summary_excludes_source_bodies(self) -> None:
        run_id = "bounded-run"
        project_id = "bounded-project"
        tasks = self._pipeline_tasks(
            analyze_status=TaskStatus.SKIPPED,
            report_status=TaskStatus.SKIPPED,
            review_status=TaskStatus.SKIPPED,
        )
        readiness_id = tasks[2].id
        self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=_terminal_complete,
            tasks=tasks,
            task_results={
                readiness_id: _readiness_snapshot(
                    task_id=readiness_id,
                    ready_for_analysis=False,
                    research_outcome="insufficient_research",
                    termination_reason="downstream_reserve_exhausted",
                ),
            },
        )
        self._add_source(
            source_id="src",
            project_id=project_id,
            run_id=run_id,
            content_text="SECRET_CONTENT_TEXT",
        )
        self._add_evidence(
            evidence_id="ev",
            source_id="src",
            project_id=project_id,
            run_id=run_id,
            statement="x" * 400,
        )
        payload = self.service.get_for_run(run_id).to_dict()
        encoded = json.dumps(payload)
        self.assertNotIn("SECRET_CONTENT_TEXT", encoded)
        self.assertNotIn("EXCERPT_SHOULD_NOT_DUMP", encoded)
        statement = payload["evidence_summary"]["items"][0]["statement"]
        self.assertLessEqual(len(statement), 280)

    def test_missing_run_raises(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.service.get_for_run("missing-run")

    def test_non_terminal_fail_closed(self) -> None:
        run = make_workflow_run(
            make_task("task-collect-evidence", executor_id="search"),
            run_id="non-terminal",
        )
        run.project_id = "p"
        run.ready()
        self.run_repo.create(run, project_id="p")
        with self.assertRaises(ResearchRunResultProjectionError):
            self.service.get_for_run("non-terminal")


if __name__ == "__main__":
    unittest.main()
