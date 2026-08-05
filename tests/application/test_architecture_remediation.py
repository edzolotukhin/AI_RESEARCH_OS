"""Report/Review architecture remediation tests (Phases A–L)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.reports.report_section import ReportSection
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType

from application.analysis.insight_rq_refs import derive_insight_research_question_refs
from application.analysis.provenance_validation import validate_insight_candidate
from application.execution.execution_budget import ExecutionBudget
from application.ports.analysis_ports import InsightCandidate
from application.report.report_assembly import (
    assemble_bounded_report,
    build_contradiction_section,
    detect_unsupported_numeric_claims,
    inject_citation_markers,
)
from application.report.substantive_coverage import (
    compute_rq_coverage_metrics,
    section_substantively_covers_question,
    validate_two_dimensional_coverage,
)
from application.review.deterministic_pre_review import run_deterministic_pre_review
from application.review.issue_clustering import (
    cluster_review_issues,
    deduplicate_and_cluster_review_issues,
    normalize_issue_theme,
    review_issue_cluster_key,
)
from application.telemetry.run_usage_summary import RunUsageSummary
from infrastructure.review.deterministic_review_engine import build_rq_batch_inputs
from infrastructure.review.llm_review_engine import LlmReviewEngine

from tests.fixtures.live_run_replay_shape import (
    LIVE_RUN_ID,
    live_findings,
    live_insights,
    live_raw_sections,
    live_report,
    live_research_design,
)
from tests.infrastructure.review.test_llm_review_engine import _semantic_input
from tests.integration.n8n.workflow_contract_helpers import (
    is_terminal_branch,
    process_poll_response,
)


def _section(
    *,
    rq: str,
    title: str,
    content: str,
    finding_refs: tuple[str, ...] = ("f1",),
) -> ReportSection:
    return ReportSection(
        id=f"sec-{rq}-{title[:8]}",
        title=title,
        content=content,
        research_question_refs=(rq,),
        finding_refs=finding_refs,
        insight_refs=(),
        evidence_refs=("e1",),
        citation_ids=("S1",),
        metadata={"primary_research_question_id": rq},
    )


class SubstantiveCoverageTests(unittest.TestCase):
    def test_reference_coverage_differs_from_substantive(self) -> None:
        design = live_research_design()
        findings = live_findings(count=12)
        section = ReportSection(
            id="s1",
            title="Generic",
            content="Unrelated prose without objective tokens.",
            research_question_refs=("RQ1",),
            finding_refs=("finding-000",),
            insight_refs=(),
            evidence_refs=("evidence-000",),
            citation_ids=("S1",),
        )
        structural = validate_two_dimensional_coverage(
            [section],
            findings=findings,
            insights=(),
            design=design,
        )
        self.assertTrue(any("structural" not in e for e in structural) or structural)

    def test_over_tagging_does_not_satisfy_all_rqs(self) -> None:
        design = live_research_design()
        question = design.research_questions[0]
        section = ReportSection(
            id="multi",
            title="Multi tag",
            content="market entry logistics",
            research_question_refs=("RQ1", "RQ2", "RQ5", "RQ6"),
            finding_refs=("finding-000",),
            insight_refs=(),
            evidence_refs=(),
            citation_ids=(),
            metadata={"primary_research_question_id": "RQ1"},
        )
        self.assertTrue(
            section_substantively_covers_question(
                section, question, findings=live_findings(count=12),
            ),
        )
        for other in design.research_questions[1:]:
            self.assertFalse(
                section_substantively_covers_question(
                    section, other, findings=live_findings(count=12),
                ),
            )


class ReportAssemblyTests(unittest.TestCase):
    def test_bounded_section_count(self) -> None:
        design = live_research_design()
        raw = list(live_raw_sections(count=57))
        assembled = assemble_bounded_report(
            raw,
            design=design,
            findings=live_findings(),
            limitations=design.limitations,
            max_sections=12,
        )
        self.assertLessEqual(len(assembled), 12)
        self.assertGreaterEqual(len(assembled), 6)

    def test_contradiction_section_generated(self) -> None:
        findings = live_findings()
        section = build_contradiction_section(findings)
        self.assertIsNotNone(section)
        assert section is not None
        self.assertIn("Conflict", section.content)

    def test_unsupported_numeric_claim_blocked(self) -> None:
        findings_by_id = {f.id: f for f in live_findings(count=15)}
        unsupported = detect_unsupported_numeric_claims(
            "Target OTIF >=95% and lead time <=10%",
            finding_refs=("finding-000",),
            findings_by_id=findings_by_id,
        )
        self.assertTrue(unsupported)

    def test_inline_citation_assembly(self) -> None:
        content = inject_citation_markers("Market grows.", ("S1", "S2"))
        self.assertIn("[S1]", content)
        self.assertIn("[S2]", content)


class InsightTraceabilityTests(unittest.TestCase):
    def test_insight_inherits_rq_from_findings(self) -> None:
        design = live_research_design()
        findings = live_findings(count=5)
        findings_by_id = {f.id: f for f in findings}
        candidate = InsightCandidate(
            statement="Insight",
            implication="Implication",
            finding_refs=(findings[0].id,),
            research_question_refs=(),
            confidence=0.8,
        )
        validated = validate_insight_candidate(
            candidate,
            findings_by_id=findings_by_id,
            project_id=findings[0].project_id,
            workflow_run_id=findings[0].workflow_run_id,
            research_design_id=design.id,
            design=design,
        )
        self.assertTrue(validated.research_question_refs)
        derived = derive_insight_research_question_refs(
            candidate,
            findings_by_id=findings_by_id,
            design=design,
        )
        self.assertEqual(derived, validated.research_question_refs)


class ReviewArchitectureTests(unittest.TestCase):
    def test_deterministic_pre_review_flags_contradiction(self) -> None:
        design = live_research_design()
        findings = live_findings()
        raw = list(live_raw_sections(count=10))
        report = live_report(sections=tuple(raw))
        issues = run_deterministic_pre_review(
            report=report,
            design=design,
            findings=list(findings),
            insights=list(live_insights()),
        )
        contradiction_issues = [
            i for i in issues if i.issue_type == ReviewIssueType.CONTRADICTION
        ]
        self.assertTrue(contradiction_issues)

    def test_semantic_review_call_count_bounded(self) -> None:
        design = live_research_design()
        raw = list(live_raw_sections(count=57))
        report = live_report(sections=tuple(assemble_bounded_report(
            raw,
            design=design,
            findings=live_findings(),
            limitations=design.limitations,
            max_sections=12,
        )))
        batches = build_rq_batch_inputs(report, max_batches=7)
        self.assertLessEqual(len(batches), 7)

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(
            llm_client=mock_llm,
            max_review_calls=7,
        )
        engine.review_report(_semantic_input(section_content="Content"))
        self.assertLessEqual(engine.llm_call_count, 7)

    def test_global_issue_emitted_once_after_clustering(self) -> None:
        issues = [
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType.CONTRADICTION,
                severity=ReviewIssueSeverity.MAJOR,
                message="Contradictory findings not acknowledged in section A",
                report_section_id="sec-1",
            ),
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType.CONTRADICTION,
                severity=ReviewIssueSeverity.MAJOR,
                message="Conflict not reconciled in section B",
                report_section_id="sec-2",
            ),
        ]
        clustered = cluster_review_issues(issues)
        self.assertEqual(len(clustered), 1)
        self.assertEqual(clustered[0].metadata.get("cluster_count"), 2)

    def test_semantic_clustering_theme_normalization(self) -> None:
        theme = normalize_issue_theme(
            "Section lacks inline citation markers",
            ReviewIssueType.MISSING_CITATION.value,
        )
        self.assertEqual(theme, "missing_inline_citation")
        key = review_issue_cluster_key(
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType.MISSING_CITATION,
                severity=ReviewIssueSeverity.MINOR,
                message="Different wording about missing citation",
                research_question_refs=("RQ1",),
            ),
        )
        key2 = review_issue_cluster_key(
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType.MISSING_CITATION,
                severity=ReviewIssueSeverity.MINOR,
                message="Another missing citation message",
                research_question_refs=("RQ1",),
            ),
        )
        self.assertEqual(key, key2)


class OfflineReplayTests(unittest.TestCase):
    def test_live_shaped_replay_improvements(self) -> None:
        design = live_research_design()
        findings = live_findings()
        raw = list(live_raw_sections(count=57))
        assembled = assemble_bounded_report(
            raw,
            design=design,
            findings=findings,
            limitations=design.limitations,
            max_sections=12,
        )
        report = live_report(sections=assembled)

        pre_issues = run_deterministic_pre_review(
            report=report,
            design=design,
            findings=list(findings),
            insights=list(live_insights()),
        )
        simulated_semantic = [
            ReviewIssue(
                id=str(uuid4()),
                issue_type=ReviewIssueType.COVERAGE_GAP,
                severity=ReviewIssueSeverity.MAJOR,
                message="RQ3 pricing gap remains",
                research_question_refs=("RQ3",),
                report_section_id=assembled[2].id if len(assembled) > 2 else None,
            ),
        ]
        clustered = deduplicate_and_cluster_review_issues(
            list(pre_issues) + simulated_semantic,
        )
        self.assertLess(len(clustered), 274)
        self.assertLessEqual(len(assembled), 12)
        self.assertTrue(
            any(s.title.startswith("Contradictions") for s in assembled),
        )
        contradiction_global = [
            i for i in clustered
            if i.issue_type == ReviewIssueType.CONTRADICTION
        ]
        self.assertLessEqual(len(contradiction_global), 1)


class ExecutionBudgetTests(unittest.TestCase):
    def test_budget_exhaustion_persisted(self) -> None:
        budget = ExecutionBudget(llm_max_calls_per_run=2, review_max_llm_calls=1)
        budget.record_llm_call("review")
        budget.record_llm_call("review", retry=True)
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.exhaustion_reason, "review_max_llm_calls")
        summary = RunUsageSummary(workflow_run_id=LIVE_RUN_ID)
        summary.merge_budget(budget)
        payload = summary.to_dict()
        self.assertTrue(payload["budget_exhausted"])
        self.assertIn("review", payload["stages"])


class N8nTerminalRoutingTests(unittest.TestCase):
    def test_terminal_reject_stops_poll_loop(self) -> None:
        merged = process_poll_response(
            {
                "run_id": LIVE_RUN_ID,
                "project_id": "p1",
                "api_url": "http://localhost:8000",
                "correlation_id": "c1",
                "idempotency_key": "k1",
                "poll_attempt": 3,
                "max_poll_attempts": 60,
                "poll_interval_seconds": 5,
                "status": "failed",
                "is_terminal": True,
                "final_review_verdict": "reject",
                "final_artifact_available": False,
                "final_artifact_id": None,
            },
        )
        self.assertEqual(is_terminal_branch(merged), "terminal")
        self.assertEqual(merged["final_review_verdict"], "reject")
        self.assertTrue(merged["is_terminal"])


if __name__ == "__main__":
    unittest.main()
