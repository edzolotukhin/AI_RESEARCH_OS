import unittest
from types import SimpleNamespace

from application.query.research_run_result import ResearchRunOutcome
from application.query.research_run_result_query_service import ResearchRunResultQueryService
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.workflow_status import WorkflowStatus
from application.research_quality.readiness_result_codec import extract_research_product_outcome


class P8D3OutcomeIntegrityTests(unittest.TestCase):
    def test_extracts_nested_and_legacy_outcomes(self):
        nested = {"task-write-report": {"shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}}}}
        self.assertEqual(extract_research_product_outcome(nested)["outcome"], "PARTIAL")
        self.assertEqual(extract_research_product_outcome({"research_product_outcome": {"outcome": "COMPLETED"}})["outcome"], "COMPLETED")
        readiness = {"task": {"shared_state": {"research_readiness": {"research_product_outcome": {"outcome": "INSUFFICIENT"}}}}}
        self.assertEqual(extract_research_product_outcome(readiness)["outcome"], "INSUFFICIENT")

    def test_rejects_missing_malformed_and_conflicting_outcomes(self):
        self.assertIsNone(extract_research_product_outcome({"task": {"shared_state": {}}}))
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"task": {"shared_state": {"research_product_outcome": "bad"}}})
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "a": {"shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}}},
                "b": {"shared_state": {"research_product_outcome": {"outcome": "COMPLETED"}}},
            })

    def test_failed_outcome_takes_precedence(self):
        result = extract_research_product_outcome({
            "a": {"shared_state": {"research_product_outcome": {"outcome": "COMPLETED"}}},
            "b": {"shared_state": {"research_product_outcome": {"outcome": "FAILED"}}},
        })
        self.assertEqual(result["outcome"], "FAILED")

    def test_rejects_unknown_or_ambiguous_payloads_independent_of_order(self):
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": {"outcome": "UNKNOWN"}}}})
        duplicate = {"outcome": "PARTIAL", "report_id": "r"}
        self.assertEqual(extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": duplicate}}, "b": {"shared_state": {"research_product_outcome": dict(duplicate)}}})["outcome"], "PARTIAL")
        differing = {"outcome": "PARTIAL", "report_id": "r2"}
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": duplicate}}, "b": {"shared_state": {"research_product_outcome": differing}}})
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}}}, "b": {"shared_state": {"research_product_outcome": {"outcome": "COMPLETED"}}}})

    def test_rejects_conflicting_failed_metadata_and_malformed_in_any_position(self):
        failed = {"outcome": "FAILED", "reason": "x"}
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": failed}}, "b": {"shared_state": {"research_product_outcome": {"outcome": "FAILED", "reason": "y"}}}})
        for payloads in (
            ("bad", {"outcome": "PARTIAL"}),
            ({"outcome": "PARTIAL"}, "bad"),
        ):
            with self.assertRaises(ValueError):
                extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": payloads[0]}}, "b": {"shared_state": {"research_product_outcome": payloads[1]}}})

    def test_structural_metadata_equality_supports_nested_values(self):
        payload = {"outcome": "PARTIAL", "metadata": {"needs": ["in-a"], "coverage": {"period": "2025"}}}
        same = {"outcome": "PARTIAL", "metadata": {"coverage": {"period": "2025"}, "needs": ["in-a"]}}
        result = extract_research_product_outcome({
            "a": {"shared_state": {"research_product_outcome": payload}},
            "b": {"shared_state": {"research_product_outcome": same}},
        })
        self.assertEqual(result, payload)
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "a": {"shared_state": {"research_product_outcome": payload}},
                "b": {"shared_state": {"research_product_outcome": {**same, "metadata": {"needs": ["in-b"]}}}},
            })
        failed = {"outcome": "FAILED", "metadata": {"diagnostics": ["x"]}}
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "a": {"shared_state": {"research_product_outcome": failed}},
                "b": {"shared_state": {"research_product_outcome": {"outcome": "FAILED", "metadata": {"diagnostics": ["y"]}}}},
            })
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
            metadata={"validation_status": "validated"},
        )

    def _derive(self, *, product="COMPLETED", findings=None, evidence=None, blocking=(), required=None, assessments=True):
        required = tuple(required or (("in-a", "in-b") if "in-b" in blocking else ("in-a",)))
        readiness = {
            "analysis_eligible_information_need_ids": ["in-a"],
            "blocking_information_need_ids": list(blocking),
        }
        if assessments:
            readiness["research_question_assessments"] = [{
                "research_question_id": "rq-1",
                "information_need_assessments": [
                    {"information_need_id": need} for need in required
                ],
            }]
        return self.service._derive_outcome(
            workflow_run=self.run, readiness_payload=readiness,
            reviews=[], latest_review=None, approved_artifact=None, artifacts=[],
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
        self.assertEqual(self._derive(findings=[self.finding], evidence=[self.evidence], blocking=("in-b",), required=("in-a", "in-b")), ResearchRunOutcome.PARTIAL)
        self.assertEqual(self._derive(product="INSUFFICIENT"), ResearchRunOutcome.INSUFFICIENT)

    def test_missing_required_need_assessments_cannot_fabricate_outcome(self):
        self.assertEqual(
            self._derive(findings=[self.finding], evidence=[self.evidence], assessments=False),
            ResearchRunOutcome.INSUFFICIENT,
        )


if __name__ == "__main__":
    unittest.main()
