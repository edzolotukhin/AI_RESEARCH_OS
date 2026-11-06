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

    def test_report_outcome_supersedes_provisional_readiness_outcome(self):
        snapshots = {
            "task-assess-research-readiness": {
                "definition_id": "task-assess-research-readiness",
                "shared_state": {
                    "research_readiness": {
                        "research_product_outcome": {"outcome": "INSUFFICIENT"},
                    },
                },
            },
            "task-write-report": {
                "definition_id": "task-write-report",
                "shared_state": {
                    "research_product_outcome": {
                        "outcome": "PARTIAL", "report_id": "r1",
                    },
                },
            },
        }
        self.assertEqual(extract_research_product_outcome(snapshots)["outcome"], "PARTIAL")
        snapshots["task-write-report"]["shared_state"]["research_product_outcome"]["outcome"] = "COMPLETED"
        self.assertEqual(extract_research_product_outcome(snapshots)["outcome"], "COMPLETED")

    def test_report_outcome_does_not_conflict_with_legacy_fallback(self):
        result = extract_research_product_outcome({
            "research_product_outcome": {"outcome": "INSUFFICIENT"},
            "task-write-report": {
                "definition_id": "task-write-report",
                "shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}},
            },
        })
        self.assertEqual(result["outcome"], "PARTIAL")

    def test_analysis_snapshot_is_provisional_before_report_stage(self):
        snapshots = {
            "task-assess-research-readiness": {
                "definition_id": "task-assess-research-readiness",
                "shared_state": {"research_product_outcome": {"outcome": "INSUFFICIENT"}},
            },
            "task-analyze": {
                "definition_id": "task-analyze",
                "shared_state": {"research_product_outcome": {"outcome": "INSUFFICIENT"}},
            },
            "task-write-report": {
                "definition_id": "task-write-report",
                "shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}},
            },
        }
        self.assertEqual(extract_research_product_outcome(snapshots)["outcome"], "PARTIAL")

    def test_analysis_snapshot_is_provisional_fallback_without_report(self):
        result = extract_research_product_outcome({
            "task-analyze": {
                "definition_id": "task-analyze",
                "shared_state": {"research_product_outcome": {"outcome": "INSUFFICIENT"}},
            },
        })
        self.assertEqual(result["outcome"], "INSUFFICIENT")

    def test_proven_post_analysis_outcome_supersedes_readiness_metadata(self):
        result = extract_research_product_outcome({
            "task-assess-research-readiness": {
                "definition_id": "task-assess-research-readiness",
                "shared_state": {
                    "research_readiness": {
                        "research_product_outcome": {
                            "outcome": "INSUFFICIENT",
                            "derivation_version": "p8d3-v1",
                            "unresolved_information_need_ids": ["in-1"],
                        },
                    },
                },
            },
            "task-analyze": {
                "definition_id": "task-analyze",
                "shared_state": {
                    "research_product_outcome": {
                        "outcome": "INSUFFICIENT",
                        "derivation_version": "p8d3-v1",
                        "authoritative_post_analysis": True,
                        "unresolved_information_need_ids": ["in-1"],
                        "reason": "no_defensible_findings",
                    },
                },
            },
        })
        self.assertTrue(result["authoritative_post_analysis"])

    def test_inherited_analysis_outcome_remains_provisional(self):
        result = extract_research_product_outcome({
            "task-assess-research-readiness": {
                "definition_id": "task-assess-research-readiness",
                "shared_state": {
                    "research_readiness": {
                        "research_product_outcome": {"outcome": "INSUFFICIENT"},
                    },
                },
            },
            "task-analyze": {
                "definition_id": "task-analyze",
                "shared_state": {
                    "research_product_outcome": {"outcome": "INSUFFICIENT"},
                },
            },
        })
        self.assertEqual(result["outcome"], "INSUFFICIENT")

    def test_report_outcome_is_independent_of_snapshot_order(self):
        report = {
            "definition_id": "task-write-report",
            "shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}},
        }
        readiness = {
            "definition_id": "task-assess-research-readiness",
            "shared_state": {
                "research_product_outcome": {"outcome": "INSUFFICIENT"},
            },
        }
        first = extract_research_product_outcome({"readiness": readiness, "report": report})
        second = extract_research_product_outcome({"report": report, "readiness": readiness})
        self.assertEqual(first, second)
        self.assertEqual(first["outcome"], "PARTIAL")

    def test_unknown_task_snapshot_is_not_authoritative(self):
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "task-unknown": {
                    "definition_id": "task-unknown",
                    "shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}},
                },
            })

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
            "a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {"outcome": "COMPLETED"}}},
            "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {"outcome": "FAILED"}}},
        })
        self.assertEqual(result["outcome"], "FAILED")

    def test_rejects_unknown_or_ambiguous_payloads_independent_of_order(self):
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"shared_state": {"research_product_outcome": {"outcome": "UNKNOWN"}}}})
        duplicate = {"outcome": "PARTIAL", "report_id": "r"}
        self.assertEqual(extract_research_product_outcome({"a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": duplicate}}, "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": dict(duplicate)}}})["outcome"], "PARTIAL")
        differing = {"outcome": "PARTIAL", "report_id": "r2"}
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": duplicate}}, "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": differing}}})
        with self.assertRaises(ValueError):
            extract_research_product_outcome({"a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {"outcome": "PARTIAL"}}}, "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {"outcome": "COMPLETED"}}}})

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
            "a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": payload}},
            "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": same}},
        })
        self.assertEqual(result, payload)
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": payload}},
                "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {**same, "metadata": {"needs": ["in-b"]}}}},
            })
        failed = {"outcome": "FAILED", "metadata": {"diagnostics": ["x"]}}
        with self.assertRaises(ValueError):
            extract_research_product_outcome({
                "a": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": failed}},
                "b": {"definition_id": "task-write-report", "shared_state": {"research_product_outcome": {"outcome": "FAILED", "metadata": {"diagnostics": ["y"]}}}},
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

    def test_outcome_derivation_accepts_empty_or_mixed_collection_types(self):
        self.assertEqual(
            self._derive(findings=[], evidence=[self.evidence]),
            ResearchRunOutcome.INSUFFICIENT,
        )
        self.assertEqual(
            self._derive(findings=[self.finding], evidence=[self.evidence]),
            ResearchRunOutcome.COMPLETED,
        )
        self.assertEqual(
            self._derive(findings=[], evidence=[]),
            ResearchRunOutcome.INSUFFICIENT,
        )
        self.assertEqual(
            self._derive(findings=None, evidence=None),
            ResearchRunOutcome.INSUFFICIENT,
        )

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
