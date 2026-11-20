import unittest

from application.evidence.evidence_extraction_diagnostics import (
    EvidenceExtractionDiagnostics,
    classify_provenance_rejection,
)
from application.evidence.evidence_result_codec import (
    extract_candidate_rejection_diagnostics,
)
from application.evidence.provenance_validation import InvalidProvenanceError


class IR1CandidateRejectionDiagnosticsTests(unittest.TestCase):
    def test_current_provenance_rejection_classes_have_typed_codes(self) -> None:
        messages = (
            "No information needs are linked to this source for the current run",
            "Unsupported Evidence candidate contract version",
            "Candidate information_need_refs are outside the run-scoped context",
            "Candidate subject continuity is unsupported for assigned needs",
            "Candidate local information-need relevance is unsupported for assigned needs",
            "Research question 'rq' is not in the run design",
            "V2 candidate requires exactly one valid information need",
            "V2 candidate references an unknown research question",
            "V2 required_aspect_refs are duplicate or excessive",
            "V2 required aspect is outside the assigned information need",
            "V2 candidate requires an executable ResearchSubject",
            "V2 subject_binding must be an object",
            "V2 candidate has a stale or unknown ResearchSubject",
            "Canonical subject binding cannot name a relation",
            "Supporting relation binding requires a relation ID",
            "V2 supporting relation is outside the assigned information need",
            "V2 supporting relation is outside the assigned research question",
            "V2 supporting relation is outside the assigned aspect scope",
            "V2 subject binding type is invalid",
            "V2 semantic justification is missing or excessive",
            "V2 geography applicability is duplicate or excessive",
            "V2 geography applicability contradicts the assigned need",
            "V2 candidate matches an explicit ResearchSubject exclusion",
            "V2 statement is unsupported by its grounded excerpt",
        )
        for message in messages:
            with self.subTest(message=message):
                error = InvalidProvenanceError(message)
                self.assertEqual(error.rejection_code, classify_provenance_rejection(message))
                self.assertTrue(error.rejection_code)

    def test_five_rejections_are_bounded_sanitized_and_deduplicated(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        for index in range(5):
            diagnostics.record_candidate_rejection(
                source_id="source-1",
                information_need_id="in-1",
                operation_id=f"operation-{index}",
                candidate_index=index,
                validation_phase="provenance",
                rejection_code="semantic_excerpt_mismatch",
                contract_version="desk_evidence_candidate_v2",
            )
        diagnostics.record_candidate_rejection(
            source_id="source-1",
            information_need_id="in-1",
            operation_id="operation-0",
            candidate_index=0,
            validation_phase="provenance",
            rejection_code="semantic_excerpt_mismatch",
            contract_version="desk_evidence_candidate_v2",
        )
        records = diagnostics.to_dict()["candidate_rejection_diagnostics"]
        self.assertEqual(len(records), 5)
        self.assertEqual([item["candidate_index"] for item in records], list(range(5)))
        self.assertTrue(all("statement" not in item and "excerpt" not in item for item in records))
        self.assertTrue(all("prompt" not in item and "content" not in item for item in records))
        self.assertLessEqual(len(str(diagnostics.to_dict())), 100_000)

    def test_accepted_candidate_has_no_rejection_record(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        self.assertEqual(diagnostics.to_dict()["candidate_rejection_diagnostics"], [])

    def test_copied_task_snapshots_merge_once_in_deterministic_order(self) -> None:
        diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run-1")
        diagnostics.record_candidate_rejection(
            source_id="source-1",
            information_need_id="in-1",
            operation_id="operation-1",
            candidate_index=1,
            validation_phase="provenance",
            rejection_code="semantic_excerpt_mismatch",
            contract_version="desk_evidence_candidate_v2",
        )
        payload = {"shared_state": {"evidence_extraction": {"diagnostics": diagnostics.to_dict()}}}
        merged = extract_candidate_rejection_diagnostics({"task-a": payload, "task-b": payload})
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["operation_id"], "operation-1")


if __name__ == "__main__":
    unittest.main()
