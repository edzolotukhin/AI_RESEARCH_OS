"""P1-08 evidence-backed Review support-context + bound acceptance tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_issue import ReviewIssueSeverity, ReviewIssueType
from domain.reviews.review_verdict import ReviewVerdict

from application.ports.review_ports import ReviewSectionInput, SemanticReviewInput
from application.review.review_support_context import (
    build_review_support_context,
    incomplete_review_coverage_issue,
    support_reference_issues,
)
from application.review.structural_review import compute_verdict
from infrastructure.review.deterministic_review_engine import build_rq_batch_inputs
from infrastructure.review.llm_review_engine import LlmReviewEngine


def _report(
    *,
    content: str,
    finding_refs: tuple[str, ...] = ("finding-1",),
    insight_refs: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = ("evidence-1",),
    run_id: str = "run-a",
    design_id: str = "design-a",
    sections: tuple[ReportSection, ...] | None = None,
) -> Report:
    if sections is None:
        sections = (
            ReportSection(
                id="section-1",
                title="Market outlook",
                content=content,
                research_question_refs=("rq-1",),
                finding_refs=finding_refs,
                insight_refs=insight_refs,
                evidence_refs=evidence_refs,
                citation_ids=("S1",),
                metadata={"primary_research_question_id": "rq-1"},
            ),
        )
    return Report(
        id="report-1",
        project_id="project-1",
        workflow_run_id=run_id,
        research_design_id=design_id,
        title="Serbia Report",
        language="en",
        sections=sections,
        executive_summary="Summary",
        limitations=("Limited public data",),
        created_at="2026-01-01T00:00:00+00:00",
        generation_method="llm",
        finding_refs=finding_refs,
        insight_refs=insight_refs,
        evidence_refs=evidence_refs,
        citation_registry={
            "S1": {
                "citation_id": "S1",
                "source_id": "source-1",
                "title": "Source",
                "canonical_url": "https://example.com",
            },
        },
        revision_number=1,
    )


def _finding(
    *,
    finding_id: str = "finding-1",
    statement: str = "Market growth was approximately 10%.",
    rationale: str = "Based on cited evidence.",
    evidence_refs: tuple[str, ...] = ("evidence-1",),
    run_id: str = "run-a",
    design_id: str = "design-a",
) -> Finding:
    return Finding(
        id=finding_id,
        project_id="project-1",
        workflow_run_id=run_id,
        research_design_id=design_id,
        statement=statement,
        rationale=rationale,
        evidence_refs=evidence_refs,
        created_at="2026-01-01T00:00:00+00:00",
        research_question_refs=("rq-1",),
        finding_type=FindingType.SYNTHESIS,
        analysis_method="llm",
    )


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    statement: str = "Serbia market grew 10%.",
    excerpt: str = "Official data shows Serbia market grew 10%.",
    run_id: str = "run-a",
    design_id: str = "design-a",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id="project-1",
        source_id="source-1",
        source_content_checksum="abc",
        workflow_run_id=run_id,
        research_design_id=design_id,
        statement=statement,
        source_excerpt=excerpt,
        created_at="2026-01-01T00:00:00+00:00",
        evidence_type=EvidenceType.DIRECT_EXCERPT,
        research_question_refs=("rq-1",),
    )


def _insight(
    *,
    insight_id: str = "insight-1",
    statement: str = "Adoption is growing among some suppliers.",
    implication: str = "Entry may target early adopters.",
    finding_refs: tuple[str, ...] = ("finding-1",),
    run_id: str = "run-a",
    design_id: str = "design-a",
) -> Insight:
    return Insight(
        id=insight_id,
        project_id="project-1",
        workflow_run_id=run_id,
        research_design_id=design_id,
        statement=statement,
        implication=implication,
        finding_refs=finding_refs,
        created_at="2026-01-01T00:00:00+00:00",
        research_question_refs=("rq-1",),
    )


def _semantic_input_with_support(
    *,
    content: str,
    findings: list[Finding],
    evidence_items: list[Evidence],
    insights: list[Insight] | None = None,
    report: Report | None = None,
) -> SemanticReviewInput:
    report = report or _report(content=content)
    support = build_review_support_context(
        report=report,
        findings=findings,
        insights=insights or [],
        evidence_items=evidence_items,
    )
    section_input = ReviewSectionInput(
        report=report,
        section_index=0,
        section_title=report.sections[0].title,
        section_content=content,
        finding_refs=report.sections[0].finding_refs,
        insight_refs=report.sections[0].insight_refs,
        citation_ids=report.sections[0].citation_ids,
        research_question_refs=report.sections[0].research_question_refs,
    )
    return SemanticReviewInput(
        project_id=report.project_id,
        workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id,
        report=report,
        brief_objectives=("Assess market growth.",),
        research_questions=("What is market growth?",),
        section_inputs=(section_input,),
        support_context=support,
    )


class ReviewSupportContextContractTests(unittest.TestCase):
    def test_case_1_supported_claim_payload_contains_support_bodies(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(llm_client=mock_llm, max_chars_per_section=8000)
        review_input = _semantic_input_with_support(
            content="The market grew by about 10%.",
            findings=[_finding()],
            evidence_items=[_evidence()],
        )
        issues = engine.review_report(review_input)
        self.assertEqual(issues, ())
        payload = mock_llm.generate.call_args[0][0].user
        self.assertIn("FINDING id=finding-1", payload)
        self.assertIn("Market growth was approximately 10%.", payload)
        self.assertIn("EVIDENCE id=evidence-1", payload)
        self.assertIn("Serbia market grew 10%.", payload)
        self.assertIn("support_context:", payload)

    def test_case_2_overstatement_negative_control(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "unsupported_claim",
                            "severity": "major",
                            "message": (
                                "Report claims 32% growth but Finding/Evidence "
                                "support only ~10%."
                            ),
                            "finding_refs": ["finding-1"],
                            "evidence_refs": ["evidence-1"],
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm)
        issues = engine.review_report(
            _semantic_input_with_support(
                content="Market grew 32%.",
                findings=[_finding()],
                evidence_items=[_evidence()],
            ),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, ReviewIssueType.UNSUPPORTED_CLAIM.value)
        self.assertEqual(issues[0].severity, "major")

    def test_case_3_evidence_contradicts_claim(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "contradiction",
                            "severity": "major",
                            "message": "Report contradicts evidence of 10% growth.",
                            "evidence_refs": ["evidence-1"],
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm)
        issues = engine.review_report(
            _semantic_input_with_support(
                content="Market contracted by 20%.",
                findings=[_finding()],
                evidence_items=[_evidence()],
            ),
        )
        self.assertEqual(issues[0].issue_type, ReviewIssueType.CONTRADICTION.value)

    def test_case_4_missing_evidence_fail_closed(self) -> None:
        support = build_review_support_context(
            report=_report(content="Claim", evidence_refs=("evidence-missing",)),
            findings=[_finding(evidence_refs=("evidence-missing",))],
            insights=[],
            evidence_items=[],
        )
        issues = support_reference_issues(support)
        self.assertTrue(any(i.issue_type == ReviewIssueType.UNSUPPORTED_CLAIM for i in issues))
        self.assertEqual(compute_verdict(issues), ReviewVerdict.REVISE)

    def test_case_5_missing_finding_fail_closed(self) -> None:
        support = build_review_support_context(
            report=_report(content="Claim", finding_refs=("finding-missing",)),
            findings=[],
            insights=[],
            evidence_items=[_evidence()],
        )
        issues = support_reference_issues(support)
        self.assertTrue(
            any(
                i.issue_type == ReviewIssueType.UNSUPPORTED_CLAIM
                and "missing" in i.message.lower()
                for i in issues
            ),
        )
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_case_6_foreign_finding_fail_closed(self) -> None:
        support = build_review_support_context(
            report=_report(content="Claim", run_id="run-a"),
            findings=[_finding(run_id="run-b")],
            insights=[],
            evidence_items=[_evidence(run_id="run-a")],
        )
        issues = support_reference_issues(support)
        self.assertTrue(any("Foreign Finding" in i.message for i in issues))
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)
        rendered = support.render_for_section_indices((0,), max_chars=4000)
        self.assertNotIn("Market growth was approximately 10%.", rendered)

    def test_case_7_foreign_evidence_fail_closed(self) -> None:
        support = build_review_support_context(
            report=_report(content="Claim", run_id="run-a"),
            findings=[_finding(run_id="run-a", evidence_refs=("evidence-1",))],
            insights=[],
            evidence_items=[_evidence(run_id="run-b")],
        )
        issues = support_reference_issues(support)
        self.assertTrue(any("Foreign Evidence" in i.message for i in issues))
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_case_8_valid_ids_unrelated_content(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "unsupported_claim",
                            "severity": "major",
                            "message": (
                                "Report market-growth claim is unrelated to "
                                "Finding about packaging colors."
                            ),
                            "finding_refs": ["finding-1"],
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm)
        issues = engine.review_report(
            _semantic_input_with_support(
                content="The market grew by about 10%.",
                findings=[
                    _finding(
                        statement="Packaging prefers green labels.",
                        rationale="Survey of packaging preferences.",
                    ),
                ],
                evidence_items=[
                    _evidence(
                        statement="Buyers prefer green packaging.",
                        excerpt="Survey excerpt about green packaging.",
                    ),
                ],
            ),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, ReviewIssueType.UNSUPPORTED_CLAIM.value)

    def test_case_9_max_chars_per_section_on_live_batch_path(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(llm_client=mock_llm, max_chars_per_section=120)
        long_content = "x" * 500
        review_input = _semantic_input_with_support(
            content=long_content,
            findings=[_finding()],
            evidence_items=[_evidence()],
        )
        engine.review_report(review_input)
        payload = mock_llm.generate.call_args[0][0].user
        # Section prose bound (not support bodies).
        section_marker = "section_content: "
        section_part = payload.split(section_marker, 1)[1].split("\nfinding_refs:", 1)[0]
        body = section_part.split("\n", 1)[1] if "\n" in section_part else section_part
        self.assertLessEqual(len(body), 120)
        self.assertNotIn("x" * 121, body)

    def test_case_10_large_support_graph_bounded(self) -> None:
        findings = [
            _finding(
                finding_id=f"finding-{i}",
                statement=("growth " * 200),
                rationale=("rationale " * 200),
                evidence_refs=(f"evidence-{i}",),
            )
            for i in range(20)
        ]
        evidence_items = [
            _evidence(
                evidence_id=f"evidence-{i}",
                statement=("evidence " * 200),
                excerpt=("excerpt " * 200),
            )
            for i in range(20)
        ]
        report = _report(
            content="Claim",
            finding_refs=tuple(f.id for f in findings),
            evidence_refs=tuple(e.id for e in evidence_items),
        )
        support = build_review_support_context(
            report=report,
            findings=findings,
            insights=[],
            evidence_items=evidence_items,
            max_support_chars_per_section=1500,
        )
        section = support.sections[0]
        self.assertTrue(section.truncated)
        self.assertGreater(len(section.omitted_finding_refs) + len(section.omitted_evidence_refs), 0)
        issues = support_reference_issues(support)
        self.assertTrue(any(i.issue_type == ReviewIssueType.STRUCTURE_ISSUE for i in issues))
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_case_11_multi_rq_bounded_and_no_silent_omit_approve(self) -> None:
        sections = tuple(
            ReportSection(
                id=f"section-{i}",
                title=f"Section {i}",
                content=("y" * 300),
                research_question_refs=(f"rq-{i}",),
                finding_refs=(f"finding-{i}",),
                insight_refs=(),
                evidence_refs=(f"evidence-{i}",),
                citation_ids=("S1",),
                metadata={"primary_research_question_id": f"rq-{i}"},
            )
            for i in range(1, 6)
        )
        report = _report(content="unused", sections=sections)
        plan = build_rq_batch_inputs(
            report,
            max_chars_per_section=50,
            max_chars_per_batch=200,
            max_batches=3,
        )
        self.assertEqual(len(plan.batches), 3)
        self.assertEqual(len(plan.omitted_batch_ids), 2)
        for batch in plan.batches:
            for part in batch.section_content.split("\n\n"):
                if "\n" in part:
                    body = part.split("\n", 1)[1]
                    self.assertLessEqual(len(body), 50)
        coverage = incomplete_review_coverage_issue(
            omitted_batch_ids=plan.omitted_batch_ids,
            max_batches=3,
        )
        self.assertEqual(coverage.issue_type, ReviewIssueType.STRUCTURE_ISSUE)
        self.assertNotEqual(compute_verdict((coverage,)), ReviewVerdict.APPROVE)

    def test_case_12_malformed_output_fail_closed(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content="not-json")
        engine = LlmReviewEngine(
            llm_client=mock_llm,
            structured_output_max_attempts=1,
        )
        from application.review.exceptions import ReviewConfigurationError

        with self.assertRaises(ReviewConfigurationError):
            engine.review_report(
                _semantic_input_with_support(
                    content="The market grew by about 10%.",
                    findings=[_finding()],
                    evidence_items=[_evidence()],
                ),
            )

    def test_case_13_support_context_rebuilds_for_revised_report(self) -> None:
        first = build_review_support_context(
            report=_report(content="Market grew 32%."),
            findings=[_finding()],
            insights=[],
            evidence_items=[_evidence()],
        )
        revised_report = _report(content="The market grew by about 10%.")
        revised_report.revision_number = 2
        second = build_review_support_context(
            report=revised_report,
            findings=[_finding()],
            insights=[],
            evidence_items=[_evidence()],
        )
        self.assertEqual(second.report_revision, 2)
        self.assertNotEqual(first.diagnostics["report_revision"], second.diagnostics["report_revision"])

    def test_case_14_unresolved_major_blocks_approve(self) -> None:
        issues = support_reference_issues(
            build_review_support_context(
                report=_report(content="Claim", finding_refs=("missing",)),
                findings=[],
                insights=[],
                evidence_items=[],
            ),
        )
        self.assertEqual(compute_verdict(issues), ReviewVerdict.REVISE)

    def test_case_15_approve_possible_when_clean(self) -> None:
        support = build_review_support_context(
            report=_report(content="The market grew by about 10%."),
            findings=[_finding()],
            insights=[],
            evidence_items=[_evidence()],
        )
        self.assertTrue(support.coverage_complete)
        self.assertEqual(support_reference_issues(support), ())
        self.assertEqual(compute_verdict(()), ReviewVerdict.APPROVE)

    def test_case_16_truncation_blocks_false_approve(self) -> None:
        findings = [
            _finding(
                finding_id=f"finding-{i}",
                statement="s" * 400,
                rationale="r" * 400,
            )
            for i in range(8)
        ]
        report = _report(
            content="Universal adoption occurred.",
            finding_refs=tuple(f.id for f in findings),
            evidence_refs=(),
        )
        support = build_review_support_context(
            report=report,
            findings=findings,
            insights=[],
            evidence_items=[],
            max_support_chars_per_section=500,
        )
        issues = support_reference_issues(support)
        self.assertTrue(any("truncated" in i.message.lower() for i in issues))
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_finding_vs_report_distinction_payload(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "unsupported_claim",
                            "severity": "major",
                            "message": (
                                "Report claims universal adoption; Finding only "
                                "supports some supplier growth."
                            ),
                            "finding_refs": ["finding-1"],
                            "insight_refs": ["insight-1"],
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm)
        report = _report(
            content="The market has universally adopted the product.",
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            evidence_refs=("evidence-1",),
        )
        issues = engine.review_report(
            _semantic_input_with_support(
                content=report.sections[0].content,
                findings=[
                    _finding(statement="Some suppliers report adoption growth."),
                ],
                insights=[_insight()],
                evidence_items=[
                    _evidence(statement="Supplier A reports growth."),
                ],
                report=report,
            ),
        )
        self.assertEqual(len(issues), 1)
        payload = mock_llm.generate.call_args[0][0].user
        self.assertIn("Some suppliers report adoption growth.", payload)
        self.assertIn("INSIGHT id=insight-1", payload)


class LlmReviewEngineBoundRegressionTests(unittest.TestCase):
    def test_section_content_is_bounded(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(llm_client=mock_llm, max_chars_per_section=120)
        long_content = "x" * 500
        report = _report(content=long_content)
        section_input = ReviewSectionInput(
            report=report,
            section_index=0,
            section_title="Market outlook",
            section_content=long_content,
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            citation_ids=("S1",),
            research_question_refs=("rq-1",),
        )
        review_input = SemanticReviewInput(
            project_id="project-1",
            workflow_run_id="run-a",
            research_design_id="design-a",
            report=report,
            brief_objectives=("Evaluate brand growth.",),
            research_questions=("What is brand growth?",),
            section_inputs=(section_input,),
        )
        engine.review_report(review_input)
        payload = mock_llm.generate.call_args[0][0].user
        section_part = payload.split("section_content: ", 1)[1].split("\nfinding_refs:", 1)[0]
        body = section_part.split("\n", 1)[1] if "\n" in section_part else section_part
        self.assertIn("x" * 120, body)
        self.assertNotIn("x" * 121, body)
        self.assertLessEqual(len(body), 120)


if __name__ == "__main__":
    unittest.main()
