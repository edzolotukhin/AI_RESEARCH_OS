from __future__ import annotations

import unittest

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.reviews.review_issue import ReviewIssueType
from domain.reviews.review_verdict import ReviewVerdict

from application.review.structural_review import compute_verdict, run_structural_review


def _sample_report(**metadata) -> Report:
    return Report(
        id="report-1",
        project_id="project-1",
        workflow_run_id="run-1",
        research_design_id="design-1",
        title="Report",
        language="en",
        sections=(
            ReportSection(
                id="section-1",
                title="Question coverage",
                content="Analysis grounded in findings.",
                research_question_refs=("rq-1",),
                finding_refs=("finding-1",),
                insight_refs=("insight-1",),
                evidence_refs=("evidence-1",),
                citation_ids=("S1",),
            ),
        ),
        executive_summary="Executive summary for Evaluate brand awareness.",
        limitations=("Desk research only.",),
        created_at="2026-01-01T00:00:00+00:00",
        generation_method="deterministic",
        finding_refs=("finding-1",),
        insight_refs=("insight-1",),
        evidence_refs=("evidence-1",),
        citation_registry={"S1": {"citation_id": "S1", "source_id": "source-1"}},
        metadata=dict(metadata),
    )


class StructuralReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = ResearchBrief.from_dict(
            {
                "title": "Brand Health",
                "business_question": "Assess market position.",
                "objectives": ["Evaluate brand awareness."],
            },
        )
        self.design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(
                    id="rq-1",
                    question="What is brand awareness?",
                    objective_refs=("Evaluate brand awareness.",),
                ),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Desk sources",
                ),
            ),
            limitations=("Desk research only.",),
        )
        self.findings = [
            Finding(
                id="finding-1",
                project_id="project-1",
                workflow_run_id="run-1",
                research_design_id="design-1",
                statement="Awareness is mixed.",
                rationale="Evidence synthesis",
                evidence_refs=("evidence-1",),
                created_at="2026-01-01T00:00:00+00:00",
                research_question_refs=("rq-1",),
            ),
        ]

    def test_clean_report_has_no_major_issues(self) -> None:
        issues = run_structural_review(
            report=_sample_report(),
            brief=self.brief,
            design=self.design,
            findings=self.findings,
        )
        major = [issue for issue in issues if issue.severity.value == "major"]
        self.assertEqual(major, [])
        self.assertEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_missing_citation_is_not_approve(self) -> None:
        section = ReportSection(
            id="section-1",
            title="Question coverage",
            content="Analysis grounded in findings.",
            research_question_refs=("rq-1",),
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            evidence_refs=("evidence-1",),
            citation_ids=("S9",),
        )
        report = Report(
            id="report-1",
            project_id="project-1",
            workflow_run_id="run-1",
            research_design_id="design-1",
            title="Report",
            language="en",
            sections=(section,),
            executive_summary="Executive summary for Evaluate brand awareness.",
            limitations=("Desk research only.",),
            created_at="2026-01-01T00:00:00+00:00",
            generation_method="deterministic",
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            evidence_refs=("evidence-1",),
            citation_registry={"S1": {"citation_id": "S1", "source_id": "source-1"}},
        )
        issues = run_structural_review(
            report=report,
            brief=self.brief,
            design=self.design,
            findings=self.findings,
        )
        self.assertTrue(
            any(issue.issue_type == ReviewIssueType.MISSING_CITATION for issue in issues),
        )
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_hidden_contradiction_is_not_approve(self) -> None:
        contradiction = Finding(
            id="finding-2",
            project_id="project-1",
            workflow_run_id="run-1",
            research_design_id="design-1",
            statement="Sources disagree on awareness levels.",
            rationale="Conflict",
            evidence_refs=("evidence-2",),
            created_at="2026-01-01T00:00:00+00:00",
            finding_type=FindingType.CONTRADICTION,
        )
        issues = run_structural_review(
            report=_sample_report(),
            brief=self.brief,
            design=self.design,
            findings=[*self.findings, contradiction],
        )
        self.assertTrue(
            any(issue.issue_type == ReviewIssueType.CONTRADICTION for issue in issues),
        )
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)

    def test_missing_limitation_is_not_approve(self) -> None:
        report = Report(
            id="report-1",
            project_id="project-1",
            workflow_run_id="run-1",
            research_design_id="design-1",
            title="Report",
            language="en",
            sections=(
                ReportSection(
                    id="section-1",
                    title="Question coverage",
                    content="Analysis grounded in findings.",
                    research_question_refs=("rq-1",),
                    finding_refs=("finding-1",),
                    insight_refs=("insight-1",),
                    evidence_refs=("evidence-1",),
                    citation_ids=("S1",),
                ),
            ),
            executive_summary="Executive summary for Evaluate brand awareness.",
            limitations=(),
            created_at="2026-01-01T00:00:00+00:00",
            generation_method="deterministic",
            finding_refs=("finding-1",),
            insight_refs=("insight-1",),
            evidence_refs=("evidence-1",),
            citation_registry={"S1": {"citation_id": "S1", "source_id": "source-1"}},
        )
        issues = run_structural_review(
            report=report,
            brief=self.brief,
            design=self.design,
            findings=self.findings,
        )
        self.assertTrue(
            any(issue.issue_type == ReviewIssueType.MISSING_LIMITATION for issue in issues),
        )
        self.assertNotEqual(compute_verdict(issues), ReviewVerdict.APPROVE)


if __name__ == "__main__":
    unittest.main()
