"""Live-shaped review regression with mocked LLM output."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_issue import ReviewIssueType
from domain.reviews.review_verdict import ReviewVerdict

from application.review.exceptions import ReviewConfigurationError, ReviewError
from application.review.review_service import ReviewService
from application.review.structural_review import compute_verdict
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
from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine
from infrastructure.review.llm_review_engine import LlmReviewEngine

from tests.infrastructure.review.test_llm_review_engine import _semantic_input


def _valid_issues_payload(**overrides) -> str:
    issue = {
        "issue_type": "unsupported_claim",
        "severity": "major",
        "message": "Report overstates growth relative to cited finding.",
        "finding_refs": ["finding-1"],
        "suggested_action": "Tone down the claim",
    }
    issue.update(overrides)
    return json.dumps({"issues": [issue]})


def _engine(llm_client, *, max_attempts: int = 3) -> LlmReviewEngine:
    return LlmReviewEngine(
        llm_client=llm_client,
        max_chars_per_section=8000,
        max_issues_per_section=5,
        max_output_tokens=4096,
        reasoning_effort="minimal",
        structured_output_max_attempts=max_attempts,
    )


class ReviewLiveShapeTests(unittest.TestCase):
    def test_a_valid_json_object_persists_issues(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=_valid_issues_payload())
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Brand A will dominate the market."),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, ReviewIssueType.UNSUPPORTED_CLAIM.value)
        stats = engine.last_section_stats
        assert stats is not None
        self.assertEqual(stats.candidate_review_count, 1)

    def test_b_prose_wrapped_json_extraction_succeeds(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=f"Here is the review:\n```json\n{_valid_issues_payload()}\n```",
        )
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Overstated claim."),
        )
        self.assertEqual(len(issues), 1)

    def test_c_malformed_json_correction_retry_succeeds(self) -> None:
        mock_llm = Mock()
        calls = {"count": 0}

        def _generate(prompt, options=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return LLMResponse(content='{"issues": [')
            return LLMResponse(content=_valid_issues_payload())

        mock_llm.generate.side_effect = _generate
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Overstated claim."),
        )
        self.assertEqual(len(issues), 1)
        self.assertGreaterEqual(calls["count"], 2)

    def test_d_truncated_output_bounded_retry(self) -> None:
        mock_llm = Mock()
        calls = {"count": 0}

        def _generate(prompt, options=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return LLMResponse(
                    content='{"issues":[{"issue_type":"unsupported_claim","message":"Partial',
                    finish_reason="length",
                )
            return LLMResponse(content='{"issues":[]}')

        mock_llm.generate.side_effect = _generate
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Section content."),
        )
        self.assertEqual(issues, ())
        self.assertGreaterEqual(calls["count"], 2)
        stats = engine.last_section_stats
        assert stats is not None
        self.assertGreaterEqual(stats.attempts, 1)

    def test_e_json_array_contract_failure_retries(self) -> None:
        mock_llm = Mock()
        calls = {"count": 0}

        def _generate(prompt, options=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return LLMResponse(content='[{"issue_type":"unsupported_claim"}]')
            return LLMResponse(content='{"issues":[]}')

        mock_llm.generate.side_effect = _generate
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Section content."),
        )
        self.assertEqual(issues, ())
        self.assertGreaterEqual(calls["count"], 2)

    def test_f_all_retries_fail_raises_without_fabricated_verdict(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content="This is prose, not JSON.")
        engine = _engine(mock_llm, max_attempts=2)
        with self.assertRaises(ReviewConfigurationError):
            engine.review_report(
                _semantic_input(section_content="Section content."),
            )
        stats = engine.last_section_stats
        assert stats is not None
        self.assertEqual(stats.candidate_review_count, 0)
        self.assertIsNotNone(stats.parse_failure_category)

    def test_g_valid_reject_verdict_remains_reject(self) -> None:
        from dataclasses import replace

        report = Report(
            id="report-reject",
            project_id="project-1",
            workflow_run_id="run-reject",
            research_design_id="design-1",
            title="Reject Report",
            language="en",
            sections=(
                ReportSection(
                    id="section-1",
                    title="Summary",
                    content="Clean content.",
                    research_question_refs=("rq-1",),
                    finding_refs=("finding-1",),
                    insight_refs=("insight-1",),
                    evidence_refs=("evidence-1",),
                    citation_ids=("S1",),
                ),
            ),
            executive_summary="Summary",
            limitations=(),
            created_at="2026-01-01T00:00:00+00:00",
            generation_method="llm",
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            evidence_refs=("evidence-1",),
            citation_registry={},
            metadata={"deterministic_review_scenario": "reject"},
        )
        engine = DeterministicReviewEngine()
        review_input = replace(
            _semantic_input(section_content="Clean content."),
            report=report,
        )
        from infrastructure.review.deterministic_review_engine import candidates_to_issues

        issues = candidates_to_issues(engine.review_report(review_input))
        self.assertEqual(compute_verdict(issues), ReviewVerdict.REJECT)

    def test_h_valid_approve_verdict(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = _engine(mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Supported claim with finding-1."),
        )
        self.assertEqual(issues, ())
        self.assertEqual(
            compute_verdict(tuple()),
            ReviewVerdict.APPROVE,
        )

    def test_review_service_wraps_parse_failure_with_diagnostics(self) -> None:
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.findings.finding import Finding
        from domain.findings.finding_type import FindingType
        from domain.planning.research_design import ResearchDesign, ResearchQuestion
        from domain.project import Project
        from domain.research_brief import ResearchBrief
        from domain.task_definition import TaskDefinition
        from domain.value_objects.executor_type import ExecutorType
        from domain.workflow_template import WorkflowTemplate
        from runtime.workflow_context import WorkflowContext

        from application.persistence.records import ArtifactRecord

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content="plain prose response")
        semantic_input = _semantic_input(section_content="Content.")
        report = semantic_input.report
        report_repo = InMemoryReportRepository()
        report_repo.create(report)
        artifact_repo = InMemoryArtifactRepository()
        artifact_repo.create(
            ArtifactRecord(
                id="artifact-1",
                project_id="project-1",
                artifact_type="report",
                title="Report",
                content="# Report",
                run_id="run-1",
                status="draft",
                version=1,
                media_type="text/markdown",
                filename="report.md",
                content_checksum="abc",
                deduplication_key="dedup-artifact",
                report_id=report.id,
            ),
        )
        finding_repo = InMemoryFindingRepository()
        finding_repo.create(
            Finding(
                id="finding-1",
                project_id="project-1",
                workflow_run_id="run-1",
                research_design_id="design-1",
                statement="Growth was 10%.",
                rationale="Source data",
                evidence_refs=("evidence-1",),
                created_at="2026-01-01T00:00:00+00:00",
                research_question_refs=("rq-1",),
                finding_type=FindingType.SYNTHESIS,
                deduplication_key="dedup-finding-1",
            ),
        )
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(
                    id="rq-1",
                    question="What is growth?",
                    objective_refs=("obj-1",),
                    priority=1,
                    rationale="",
                ),
            ),
            information_needs=(),
            source_strategy=(),
            analysis_plan=(),
            deliverable_plan=("Summary",),
            assumptions=(),
            limitations=(),
            language="en",
        )
        report_service = Mock()
        report_service._resolve_design.return_value = design
        report_service._resolve_brief.return_value = Mock(objectives=("Evaluate growth.",))
        template = WorkflowTemplate(
            id="template-review",
            name="Review",
            task_definitions=[
                TaskDefinition(
                    id="task-review",
                    name="Review",
                    executor_id="review",
                    executor_type=ExecutorType.AGENT,
                ),
            ],
            research_design_snapshot=design,
            research_brief_snapshot=ResearchBrief(
                title="T",
                business_question="Q",
                deliverables=("Summary",),
                language="en",
            ),
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(
            project=Project(id="project-1", name="P"),
            workflow_template=template,
            workflow_run=run,
        )
        review_service = ReviewService(
            semantic_review_engine=_engine(mock_llm, max_attempts=1),
            finding_repository=finding_repo,
            insight_repository=InMemoryInsightRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            report_repository=report_repo,
            artifact_repository=artifact_repo,
            review_repository=InMemoryReviewRepository(),
            report_service=report_service,
            max_revision_attempts=1,
        )

        with self.assertRaises(ReviewError) as ctx:
            review_service.review_for_context(context)

        message = str(ctx.exception)
        self.assertIn("parse_failure_category", message)
        self.assertIn("run-1", message)


if __name__ == "__main__":
    unittest.main()
