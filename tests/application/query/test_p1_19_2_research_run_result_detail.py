"""P1-19.2 offline acceptance for ResearchRunResult detail projection."""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import ArtifactRecord
from application.query.research_run_result import (
    MAX_DETAIL_COLLECTION_ITEMS,
    REPORT_SECTION_CONTENT_BOUND,
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
from domain.reports.report_section import ReportSection
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
from tests.application.query.test_p1_18_1_research_run_result_query_service import (
    ResearchRunResultQueryServiceTests,
    _ReadOnlyGuard,
    _readiness_snapshot,
    _terminal_complete,
    _terminal_fail,
)


class ResearchRunResultDetailQueryServiceTests(ResearchRunResultQueryServiceTests):
    def _add_report_with_sections(
        self,
        *,
        report_id: str,
        project_id: str,
        run_id: str,
        revision_number: int,
        sections: tuple[ReportSection, ...],
        finding_refs: tuple[str, ...] = (),
        insight_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        executive_summary: str = "Executive summary body",
        limitations: tuple[str, ...] = ("limitation-a",),
        citation_registry: dict[str, dict[str, Any]] | None = None,
        previous_report_id: str | None = None,
    ) -> Report:
        report = Report(
            id=report_id,
            project_id=project_id,
            workflow_run_id=run_id,
            research_design_id="design-1",
            title=f"Report {revision_number}",
            language="en",
            sections=sections,
            executive_summary=executive_summary,
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

    def _seed_approved_fixture(self, *, run_id: str, project_id: str) -> None:
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
        self.source_repo.create(
            Source(
                id="src-1",
                project_id=project_id,
                url="https://publisher.example/report",
                canonical_url="https://publisher.example/report",
                title="Publisher Report",
                publisher="Example Publisher",
                retrieved_at="2026-08-11T00:00:00+00:00",
                workflow_run_refs=(run_id,),
                retrieval_status=RetrievalStatus.ACQUIRED,
                content_text="FULL_SOURCE_BODY_MUST_NOT_LEAK",
            ),
        )
        self.evidence_repo.create(
            Evidence(
                id="ev-1",
                project_id=project_id,
                source_id="src-1",
                source_content_checksum="checksum",
                workflow_run_id=run_id,
                research_design_id="design-1",
                statement="Canonical evidence statement",
                source_excerpt="Canonical persisted excerpt",
                created_at="2026-08-11T00:00:00+00:00",
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key="ev-1",
            ),
        )
        self._add_finding(
            finding_id="f-1",
            evidence_ids=("ev-1",),
            project_id=project_id,
            run_id=run_id,
            statement="Canonical finding",
        )
        self._add_insight(
            insight_id="i-1",
            finding_ids=("f-1",),
            project_id=project_id,
            run_id=run_id,
        )
        self._add_report_with_sections(
            report_id="rep-1",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            sections=(
                ReportSection(
                    id="sec-1",
                    title="Market Overview",
                    content="Section body with analytical detail.",
                    finding_refs=("f-1",),
                    insight_refs=("i-1",),
                    evidence_refs=("ev-1",),
                    citation_ids=("c1",),
                ),
            ),
            finding_refs=("f-1",),
            insight_refs=("i-1",),
            evidence_refs=("ev-1",),
            citation_registry={"c1": {"source_id": "src-1", "citation_id": "c1"}},
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

    def test_case_01_approved_complete_detail(self) -> None:
        run_id = "detail-approved-run"
        project_id = "detail-approved-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        detail = self.service.get_detail_for_run(run_id)
        payload = detail.to_dict()

        self.assertEqual(detail.result.outcome, ResearchRunOutcome.APPROVED)
        self.assertIn("detail", payload)
        self.assertEqual(len(payload["detail"]["sources"]), 1)
        self.assertEqual(payload["detail"]["sources"][0]["title"], "Publisher Report")
        self.assertEqual(
            payload["detail"]["sources"][0]["publisher"],
            "Example Publisher",
        )
        self.assertEqual(
            payload["detail"]["evidence"][0]["source_excerpt"]["value"],
            "Canonical persisted excerpt",
        )
        self.assertIsNotNone(payload["detail"]["report"])
        self.assertEqual(len(payload["detail"]["report"]["sections"]), 1)
        self.assertEqual(
            payload["detail"]["report"]["sections"][0]["content"]["value"],
            "Section body with analytical detail.",
        )
        self.assertIsNotNone(payload["detail"]["review"])

    def test_case_02_not_ready_without_invented_entities(self) -> None:
        run_id = "detail-not-ready-run"
        project_id = "detail-not-ready-project"
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
            },
        )
        self._add_source(source_id="src-nr", project_id=project_id, run_id=run_id)
        self._add_evidence(
            evidence_id="ev-nr",
            source_id="src-nr",
            project_id=project_id,
            run_id=run_id,
        )

        detail = self.service.get_detail_for_run(run_id)
        payload = detail.to_dict()

        self.assertEqual(detail.result.outcome, ResearchRunOutcome.NOT_READY)
        self.assertIsNone(payload["detail"]["report"])
        self.assertEqual(payload["detail"]["findings"], [])
        self.assertEqual(payload["detail"]["insights"], [])
        self.assertIsNone(payload["detail"]["review"])
        self.assertGreaterEqual(len(payload["detail"]["evidence"]), 1)
        self.assertGreaterEqual(len(payload["detail"]["sources"]), 1)

    def test_case_03_quality_rejected_exposes_review_issues(self) -> None:
        run_id = "detail-quality-rejected-run"
        project_id = "detail-quality-rejected-project"
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
        self._add_report_with_sections(
            report_id="rep-qr",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            sections=(
                ReportSection(
                    id="sec-qr",
                    title="Rejected Section",
                    content="Rejected report body",
                ),
            ),
        )
        self._add_artifact(
            artifact_id="art-rej",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-qr",
            status="rejected",
            dedup_suffix="rej",
        )
        self.review_repo.create(
            ReviewResult(
                id="rev-qr",
                project_id=project_id,
                workflow_run_id=run_id,
                research_design_id="design-1",
                report_id="rep-qr",
                review_attempt=2,
                verdict=ReviewVerdict.REVISE,
                quality_dimensions=(),
                issues=(
                    ReviewIssue(
                        id="issue-qr",
                        issue_type=ReviewIssueType.MISSING_CITATION,
                        severity=ReviewIssueSeverity.MAJOR,
                        message="Missing citation in section",
                        report_section_id="sec-qr",
                    ),
                ),
                summary="Quality rejected summary",
                review_method="test",
                created_at="2026-08-11T02:00:00+00:00",
                deduplication_key="rev-qr",
            ),
        )

        detail = self.service.get_detail_for_run(run_id)
        payload = detail.to_dict()

        self.assertEqual(detail.result.outcome, ResearchRunOutcome.QUALITY_REJECTED)
        self.assertIsNotNone(payload["detail"]["report"])
        self.assertIsNotNone(payload["detail"]["review"])
        self.assertEqual(payload["detail"]["review"]["verdict"], "revise")
        self.assertEqual(len(payload["detail"]["review"]["issues"]), 1)
        self.assertEqual(
            payload["detail"]["review"]["issues"][0]["message"]["value"],
            "Missing citation in section",
        )

    def test_case_04_execution_failed_safe_detail(self) -> None:
        run_id = "detail-execution-failed-run"
        project_id = "detail-execution-failed-project"
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

        detail = self.service.get_detail_for_run(run_id)
        payload = json.dumps(detail.to_dict())

        self.assertEqual(detail.result.outcome, ResearchRunOutcome.EXECUTION_FAILED)
        self.assertNotIn("Traceback", payload)
        self.assertNotIn("Exception", payload)

    def test_case_05_finding_evidence_source_resolution(self) -> None:
        run_id = "detail-provenance-run"
        project_id = "detail-provenance-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        detail = self.service.get_detail_for_run(run_id)
        link = next(
            item
            for item in detail.result.provenance_summary.links
            if item.finding_id == "f-1"
        )
        evidence_by_id = {item.id: item for item in detail.detail.evidence}
        source_by_id = {item.id: item for item in detail.detail.sources}

        self.assertEqual(link.finding_id, "f-1")
        self.assertEqual(link.evidence_id, "ev-1")
        self.assertEqual(link.source_id, "src-1")
        self.assertIn(link.evidence_id, evidence_by_id)
        self.assertIn(link.source_id, source_by_id)
        self.assertEqual(
            evidence_by_id["ev-1"].source_excerpt.value,
            "Canonical persisted excerpt",
        )
        self.assertEqual(source_by_id["src-1"].title, "Publisher Report")

    def test_case_06_report_section_refs_resolve(self) -> None:
        run_id = "detail-section-refs-run"
        project_id = "detail-section-refs-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        detail = self.service.get_detail_for_run(run_id)
        section = detail.detail.report.sections[0]
        finding_ids = {item.id for item in detail.detail.findings}
        insight_ids = {item.id for item in detail.detail.insights}
        evidence_ids = {item.id for item in detail.detail.evidence}

        self.assertTrue(set(section.finding_refs).issubset(finding_ids))
        self.assertTrue(set(section.insight_refs).issubset(insight_ids))
        self.assertTrue(set(section.evidence_refs).issubset(evidence_ids))

    def test_case_07_foreign_cross_run_reference_not_hydrated(self) -> None:
        run_id = "detail-run-a"
        foreign_run_id = "detail-run-b"
        project_id = "detail-foreign-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        self.source_repo.create(
            Source(
                id="src-foreign",
                project_id=project_id,
                url="https://foreign.example",
                canonical_url="https://foreign.example",
                title="Foreign Source",
                retrieved_at="2026-08-11T00:00:00+00:00",
                workflow_run_refs=(foreign_run_id,),
                retrieval_status=RetrievalStatus.ACQUIRED,
                content_text="FOREIGN_BODY",
            ),
        )
        self.evidence_repo.create(
            Evidence(
                id="ev-foreign",
                project_id=project_id,
                source_id="src-foreign",
                source_content_checksum="checksum",
                workflow_run_id=foreign_run_id,
                research_design_id="design-1",
                statement="Foreign evidence",
                source_excerpt="Foreign excerpt",
                created_at="2026-08-11T00:00:00+00:00",
                deduplication_key="ev-foreign",
            ),
        )

        detail = self.service.get_detail_for_run(run_id)
        source_ids = {item.id for item in detail.detail.sources}
        evidence_ids = {item.id for item in detail.detail.evidence}

        self.assertNotIn("src-foreign", source_ids)
        self.assertNotIn("ev-foreign", evidence_ids)
        self.assertNotIn("FOREIGN_BODY", json.dumps(detail.to_dict()))

    def test_case_08_missing_entity_fail_closed(self) -> None:
        run_id = "detail-missing-entity-run"
        project_id = "detail-missing-entity-project"
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
            report_id="rep-missing",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            finding_refs=("missing-finding",),
        )
        self._add_artifact(
            artifact_id="art-missing",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-missing",
            status="rejected",
            dedup_suffix="missing",
        )
        self._add_review(
            review_id="rev-missing",
            report_id="rep-missing",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REJECT,
        )

        detail = self.service.get_detail_for_run(run_id)
        unresolved = detail.result.provenance_summary.unresolved_refs
        self.assertTrue(any(item["id"] == "missing-finding" for item in unresolved))

    def test_case_09_source_title_publisher_url_exposed(self) -> None:
        run_id = "detail-source-card-run"
        project_id = "detail-source-card-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        source = self.service.get_detail_for_run(run_id).detail.sources[0]
        self.assertEqual(source.title, "Publisher Report")
        self.assertEqual(source.publisher, "Example Publisher")
        self.assertEqual(source.url, "https://publisher.example/report")

    def test_case_10_evidence_source_excerpt_canonical(self) -> None:
        run_id = "detail-excerpt-run"
        project_id = "detail-excerpt-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        excerpt = (
            self.service.get_detail_for_run(run_id).detail.evidence[0].source_excerpt.value
        )
        self.assertEqual(excerpt, "Canonical persisted excerpt")

    def test_case_11_collection_bounding_metadata(self) -> None:
        run_id = "detail-collection-bound-run"
        project_id = "detail-collection-bound-project"
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
        for index in range(MAX_DETAIL_COLLECTION_ITEMS + 5):
            self._add_source(
                source_id=f"src-{index}",
                project_id=project_id,
                run_id=run_id,
            )

        truncation = self.service.get_detail_for_run(run_id).detail.truncation
        self.assertTrue(truncation.collection_truncated)
        self.assertGreater(
            truncation.total_counts["sources"],
            MAX_DETAIL_COLLECTION_ITEMS,
        )

    def test_case_12_full_report_sections_available(self) -> None:
        run_id = "detail-report-sections-run"
        project_id = "detail-report-sections-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        report = self.service.get_detail_for_run(run_id).detail.report
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report.sections[0].title, "Market Overview")
        self.assertIn("analytical detail", report.sections[0].content.value)

    def test_case_13_review_issue_detail_available(self) -> None:
        run_id = "detail-review-issues-run"
        project_id = "detail-review-issues-project"
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
        self._add_report_with_sections(
            report_id="rep-issues",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            sections=(
                ReportSection(
                    id="sec-issues",
                    title="Issues Section",
                    content="Body",
                ),
            ),
        )
        self._add_artifact(
            artifact_id="art-issues",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-issues",
            status="rejected",
            dedup_suffix="issues",
        )
        self.review_repo.create(
            ReviewResult(
                id="rev-issues",
                project_id=project_id,
                workflow_run_id=run_id,
                research_design_id="design-1",
                report_id="rep-issues",
                review_attempt=1,
                verdict=ReviewVerdict.REJECT,
                quality_dimensions=(),
                issues=(
                    ReviewIssue(
                        id="issue-13",
                        issue_type=ReviewIssueType.UNSUPPORTED_CLAIM,
                        severity=ReviewIssueSeverity.MINOR,
                        message="Unsupported claim text",
                        report_section_id="sec-issues",
                    ),
                ),
                summary="Rejected",
                review_method="test",
                created_at="2026-08-11T00:00:00+00:00",
                deduplication_key="rev-issues",
            ),
        )

        detail = self.service.get_detail_for_run(run_id)
        issue = detail.detail.review.issues[0]
        self.assertEqual(issue.severity, "minor")
        self.assertEqual(issue.report_section_id, "sec-issues")

    def test_case_14_no_source_content_text(self) -> None:
        run_id = "detail-no-source-body-run"
        project_id = "detail-no-source-body-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        payload = json.dumps(self.service.get_detail_for_run(run_id).to_dict())
        self.assertNotIn("FULL_SOURCE_BODY_MUST_NOT_LEAK", payload)
        self.assertNotIn("content_text", payload)

    def test_case_16_read_only_no_writes(self) -> None:
        run_id = "detail-read-only-run"
        project_id = "detail-read-only-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        guarded = ResearchRunResultQueryService(
            workflow_run_repository=_ReadOnlyGuard(self.run_repo),
            source_repository=_ReadOnlyGuard(self.source_repo),
            evidence_repository=_ReadOnlyGuard(self.evidence_repo),
            finding_repository=_ReadOnlyGuard(self.finding_repo),
            insight_repository=_ReadOnlyGuard(self.insight_repo),
            report_repository=_ReadOnlyGuard(self.report_repo),
            review_repository=_ReadOnlyGuard(self.review_repo),
            artifact_repository=_ReadOnlyGuard(self.artifact_repo),
        )
        guarded.get_detail_for_run(run_id)

    def test_case_18_backward_compatible_summary(self) -> None:
        run_id = "detail-backcompat-run"
        project_id = "detail-backcompat-project"
        self._seed_approved_fixture(run_id=run_id, project_id=project_id)

        summary = self.service.get_for_run(run_id).to_dict()
        detail = self.service.get_detail_for_run(run_id).to_dict()

        for key, value in summary.items():
            self.assertEqual(detail[key], value)

    def test_case_22_deterministic_ordering(self) -> None:
        run_id = "detail-order-run"
        project_id = "detail-order-project"
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
        for source_id in ("src-z", "src-a", "src-m"):
            self._add_source(source_id=source_id, project_id=project_id, run_id=run_id)

        first = [
            item.id
            for item in self.service.get_detail_for_run(run_id).detail.sources
        ]
        second = [
            item.id
            for item in self.service.get_detail_for_run(run_id).detail.sources
        ]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))

    def test_case_23_report_content_truncation_explicit(self) -> None:
        run_id = "detail-report-trunc-run"
        project_id = "detail-report-trunc-project"
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
        long_content = "X" * (REPORT_SECTION_CONTENT_BOUND + 50)
        self._add_report_with_sections(
            report_id="rep-trunc",
            project_id=project_id,
            run_id=run_id,
            revision_number=1,
            sections=(
                ReportSection(
                    id="sec-trunc",
                    title="Long Section",
                    content=long_content,
                ),
            ),
        )
        self._add_artifact(
            artifact_id="art-trunc",
            project_id=project_id,
            run_id=run_id,
            report_id="rep-trunc",
            status="rejected",
            dedup_suffix="trunc",
        )
        self._add_review(
            review_id="rev-trunc",
            report_id="rep-trunc",
            project_id=project_id,
            run_id=run_id,
            attempt=1,
            verdict=ReviewVerdict.REJECT,
        )

        detail = self.service.get_detail_for_run(run_id)
        section = detail.detail.report.sections[0]
        self.assertTrue(section.content.truncated)
        self.assertGreater(section.content.original_length, REPORT_SECTION_CONTENT_BOUND)
        self.assertIn("sec-trunc", detail.detail.truncation.section_truncated_ids)

    def test_case_24_cross_run_ownership_enforcement(self) -> None:
        self.test_case_07_foreign_cross_run_reference_not_hydrated()

    def test_case_25_four_outcomes_distinct(self) -> None:
        fixtures = [
            ("detail-approved-run", "detail-approved-project", ResearchRunOutcome.APPROVED),
            ("detail-not-ready-run", "detail-not-ready-project", ResearchRunOutcome.NOT_READY),
            (
                "detail-quality-rejected-run",
                "detail-quality-rejected-project",
                ResearchRunOutcome.QUALITY_REJECTED,
            ),
            (
                "detail-execution-failed-run",
                "detail-execution-failed-project",
                ResearchRunOutcome.EXECUTION_FAILED,
            ),
        ]
        self.test_case_01_approved_complete_detail()
        self.test_case_02_not_ready_without_invented_entities()
        self.test_case_03_quality_rejected_exposes_review_issues()
        self.test_case_04_execution_failed_safe_detail()

        outcomes = {
            self.service.get_detail_for_run(run_id).result.outcome
            for run_id, _, _ in fixtures
        }
        expected = {item[2] for item in fixtures}
        self.assertEqual(outcomes, expected)

    def test_non_terminal_raises(self) -> None:
        run_id = "detail-non-terminal-run"
        project_id = "detail-non-terminal-project"
        tasks = self._pipeline_tasks()
        run = self._seed_run(
            run_id=run_id,
            project_id=project_id,
            terminal=lambda item: None,
            tasks=tasks,
            task_results={},
        )
        run.ready()
        run.start()
        self.run_repo.save(run, expected_version=1, task_results={})

        with self.assertRaises(ResearchRunResultProjectionError):
            self.service.get_detail_for_run(run_id)

    def test_unknown_run_raises(self) -> None:
        with self.assertRaises(EntityNotFoundError):
            self.service.get_detail_for_run("missing-run")


if __name__ == "__main__":
    unittest.main()
