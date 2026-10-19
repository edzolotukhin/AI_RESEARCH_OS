from __future__ import annotations

import unittest

from application.ports.report_ports import ReportSectionCandidate
from application.report.substantive_coverage import (
    validate_mandatory_rq_bindings,
    validate_mandatory_rq_candidate_binding,
)
from domain.reports.report_section import ReportSection


class MandatoryReportBindingTests(unittest.TestCase):
    contract = {"rq2": ("finding-2a", "finding-2b")}

    def test_explicit_rq_and_authoritative_finding_pass(self) -> None:
        section = ReportSection(
            id="section-1", title="RQ2", content="supported",
            research_question_refs=("rq2",), finding_refs=("finding-2a",),
            insight_refs=(), evidence_refs=(), citation_ids=(), metadata={},
        )
        self.assertEqual(validate_mandatory_rq_bindings([section], mandatory_rq_findings=self.contract), ())

    def test_missing_explicit_binding_fails(self) -> None:
        section = ReportSection(
            id="section-1", title="RQ2", content="supported",
            research_question_refs=(), finding_refs=("finding-2a",),
            insight_refs=(), evidence_refs=(), citation_ids=(), metadata={},
        )
        self.assertEqual(
            validate_mandatory_rq_bindings([section], mandatory_rq_findings=self.contract),
            ("mandatory_rq_finding_binding_missing:rq2",),
        )

    def test_candidate_partial_binding_is_rejected(self) -> None:
        candidate = ReportSectionCandidate(
            title="RQ2", content="supported", finding_refs=("finding-2a",),
        )
        self.assertEqual(
            validate_mandatory_rq_candidate_binding(
                candidate, mandatory_rq_findings=self.contract,
            ),
            ("mandatory_rq_finding_binding_missing:rq2",),
        )

    def test_candidate_wrong_finding_for_explicit_rq_is_rejected(self) -> None:
        candidate = ReportSectionCandidate(
            title="RQ2", content="supported", research_question_refs=("rq2",),
            finding_refs=("finding-other",),
        )
        self.assertEqual(
            validate_mandatory_rq_candidate_binding(
                candidate, mandatory_rq_findings=self.contract,
            ),
            ("mandatory_rq_finding_binding_missing:rq2",),
        )


if __name__ == "__main__":
    unittest.main()
