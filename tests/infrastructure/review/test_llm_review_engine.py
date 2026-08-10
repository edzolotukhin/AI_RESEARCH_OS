"""Unit tests for production LLM semantic review engine."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_issue import ReviewIssueType

from application.ports.review_ports import ReviewSectionInput, SemanticReviewInput
from infrastructure.review.llm_review_engine import LlmReviewEngine


def _semantic_input(*, section_content: str) -> SemanticReviewInput:
    report = Report(
        id="report-1",
        project_id="project-1",
        workflow_run_id="run-1",
        research_design_id="design-1",
        title="Brand Report",
        language="en",
        sections=(
            ReportSection(
                id="section-1",
                title="Market outlook",
                content=section_content,
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
        citation_registry={
            "S1": {
                "citation_id": "S1",
                "source_id": "source-1",
                "title": "Source",
                "canonical_url": "https://example.com",
                "published_at": None,
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "source_type": "web",
            },
        },
    )
    section_input = ReviewSectionInput(
        report=report,
        section_index=0,
        section_title="Market outlook",
        section_content=section_content,
        finding_refs=("finding-1",),
        insight_refs=("insight-1",),
        citation_ids=("S1",),
        research_question_refs=("rq-1",),
    )
    return SemanticReviewInput(
        project_id="project-1",
        workflow_run_id="run-1",
        research_design_id="design-1",
        report=report,
        brief_objectives=("Evaluate brand growth.",),
        research_questions=("What is brand growth?",),
        section_inputs=(section_input,),
    )


class LlmReviewEngineTests(unittest.TestCase):
    def test_unsupported_claim_from_mocked_structured_output(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "unsupported_claim",
                            "severity": "major",
                            "message": (
                                "Report claims guaranteed market dominance, but the "
                                "referenced finding only states 10% growth."
                            ),
                            "finding_refs": ["finding-1"],
                            "suggested_action": "Tone down the claim or add support",
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm, max_chars_per_section=8000)
        review_input = _semantic_input(
            section_content=(
                "Brand A grew 10% last year. Brand A is guaranteed to dominate "
                "the market next year."
            ),
        )

        issues = engine.review_report(review_input)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, ReviewIssueType.UNSUPPORTED_CLAIM.value)
        self.assertEqual(issues[0].severity, "major")
        self.assertEqual(issues[0].finding_refs, ("finding-1",))
        self.assertEqual(issues[0].report_section_id, "section-1")

    def test_foreign_refs_are_rejected(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "unsupported_claim",
                            "severity": "major",
                            "message": "Foreign refs should be dropped",
                            "finding_refs": ["finding-foreign"],
                        },
                    ],
                },
            ),
        )
        engine = LlmReviewEngine(llm_client=mock_llm)
        issues = engine.review_report(
            _semantic_input(section_content="Overstated claim."),
        )
        self.assertEqual(issues, ())

    def test_section_content_is_bounded(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(llm_client=mock_llm, max_chars_per_section=120)
        long_content = "x" * 500
        review_input = _semantic_input(section_content=long_content)

        engine.review_report(review_input)

        payload = mock_llm.generate.call_args[0][0].user
        section_part = payload.split("section_content: ", 1)[1].split("\nfinding_refs:", 1)[0]
        body = section_part.split("\n", 1)[1] if "\n" in section_part else section_part
        self.assertIn("x" * 120, body)
        self.assertNotIn("x" * 121, body)
        self.assertLessEqual(len(body), 120)
        # Live path may include support_context header; keep total request reasonable.
        self.assertLessEqual(engine.max_input_chars_per_request(review_input), 2500)


if __name__ == "__main__":
    unittest.main()
