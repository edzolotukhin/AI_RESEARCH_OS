import unittest
from types import SimpleNamespace

from application.query.research_run_result import ResearchRunOutcome
from application.query.research_run_result_query_service import ResearchRunResultQueryService
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.workflow_status import WorkflowStatus


class P8D3OutcomeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.service = ResearchRunResultQueryService.__new__(ResearchRunResultQueryService)
        self.run = SimpleNamespace(id="run", project_id="project", status=WorkflowStatus.COMPLETED)
        self.evidence = Evidence(
            id="e1", project_id="project", source_id="s", source_content_checksum="c",
            workflow_run_id="run", research_design_id="design", statement="fact",
            source_excerpt="fact", created_at="now", information_need_refs=("in-a",),
        )
        self.finding = Finding(
            id="f1", project_id="project", workflow_run_id="run",
            research_design_id="design", statement="conclusion", rationale="r",
            evidence_refs=("e1",), information_need_refs=("in-a",), created_at="now",
        )

    def _derive(self, *, product="COMPLETED", findings=None, evidence=None, blocking=()):
        return self.service._derive_outcome(
            workflow_run=self.run, readiness_payload={
                "analysis_eligible_information_need_ids": ["in-a"],
                "blocking_information_need_ids": list(blocking),
            }, reviews=[], latest_review=None, approved_artifact=None, artifacts=[],
            product_outcome={"outcome": product}, findings=findings or [],
            evidence=evidence or [],
        )

    def test_valid_finding_and_evidence_complete(self):
        self.assertEqual(self._derive(findings=[self.finding], evidence=[self.evidence]), ResearchRunOutcome.COMPLETED)

    def test_stale_foreign_or_unsupported_finding_is_insufficient(self):
        stale = Evidence(**{**self.evidence.__dict__, "workflow_run_id": "old"})
        foreign = Finding(**{**self.finding.__dict__, "project_id": "other"})
        unsupported = Finding(**{**self.finding.__dict__, "information_need_refs": ("in-b",)})
        for finding, evidence in ((self.finding, [stale]), (foreign, [self.evidence]), (unsupported, [self.evidence])):
            self.assertEqual(self._derive(findings=[finding], evidence=evidence), ResearchRunOutcome.INSUFFICIENT)

    def test_failed_precedence_survives_later_completion_event(self):
        self.assertEqual(self._derive(product="FAILED", findings=[self.finding], evidence=[self.evidence]), ResearchRunOutcome.FAILED)

    def test_partial_and_budget_stop(self):
        self.assertEqual(self._derive(findings=[self.finding], evidence=[self.evidence], blocking=("in-b",)), ResearchRunOutcome.PARTIAL)
        self.assertEqual(self._derive(product="INSUFFICIENT"), ResearchRunOutcome.INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
