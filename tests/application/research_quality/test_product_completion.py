import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from application.persistence.exceptions import AccessDeniedError
from application.query.research_run_result_query_service import ResearchRunResultQueryService
from application.research_quality.product_completion import (
    ProductCompletionFacts,
    ProductCompletionStatus,
    evaluate_product_completion,
)


def complete_facts(**overrides):
    values = dict(
        run_id="run-1", project_id="project-1", report_id="report-1",
        report_revision=3, workflow_terminal=True, workflow_failed=False,
        research_outcome="COMPLETED", report_claims_valid=True,
        review_approved=True, review_revision_aligned=True,
        h3_authority_valid=True, provenance_valid=True,
        pdf_terminal=True, pdf_integrity_valid=True,
        pdf_provenance_valid=True, pptx_terminal_success=True,
        pptx_integrity_valid=True, pptx_provenance_valid=True,
    )
    values.update(overrides)
    return ProductCompletionFacts(**values)


def query_service_with_delivery_failure(error):
    run = SimpleNamespace(
        id="run-1", project_id="project-1", is_terminal=False,
        status=SimpleNamespace(value="created"),
    )
    report = SimpleNamespace(id="report-1", project_id="project-1", revision_number=1)
    workflow_runs = Mock()
    workflow_runs.get_by_id.return_value = run
    reports = Mock()
    reports.list_for_project.return_value = [report]
    project_service = Mock()
    project_service.get_project.return_value = SimpleNamespace(owner_principal_id="owner")
    deliverables = Mock()
    deliverables.source.side_effect = error
    report_claims = Mock()
    report_claims.list_for_report.return_value = []
    reviews = Mock()
    reviews.list_for_project.return_value = []
    return ResearchRunResultQueryService(
        workflow_run_repository=workflow_runs,
        source_repository=Mock(), evidence_repository=Mock(),
        finding_repository=Mock(), insight_repository=Mock(),
        report_repository=reports, review_repository=reviews,
        artifact_repository=Mock(), project_service=project_service,
        deliverables_service=deliverables, report_claim_repository=report_claims,
    )


class ProductCompletionTests(unittest.TestCase):
    def test_complete_facts_are_ready(self):
        result = evaluate_product_completion(complete_facts(), evaluated_at="fixed")
        self.assertEqual(result.status, ProductCompletionStatus.READY)
        self.assertEqual(result.blocking_codes, ())
        self.assertEqual(result.evaluated_at, "fixed")

    def test_missing_delivery_facts_are_not_ready(self):
        result = evaluate_product_completion(
            complete_facts(review_approved=False, pdf_terminal=False, pptx_terminal_success=False),
            evaluated_at="fixed",
        )
        self.assertEqual(result.status, ProductCompletionStatus.NOT_READY)
        self.assertEqual(
            result.blocking_codes,
            ("h3_review_not_approved", "pdf_not_terminal", "pptx_not_terminal_success"),
        )

    def test_partial_and_insufficient_are_not_ready(self):
        for outcome in ("PARTIAL", "INSUFFICIENT"):
            with self.subTest(outcome=outcome):
                result = evaluate_product_completion(
                    complete_facts(research_outcome=outcome), evaluated_at="fixed",
                )
                self.assertEqual(result.status, ProductCompletionStatus.NOT_READY)
                self.assertEqual(result.blocking_codes, ("research_outcome_not_completed",))

    def test_conflicting_identifiers_are_failed(self):
        result = evaluate_product_completion(
            complete_facts(contradictory_identifiers=True), evaluated_at="fixed",
        )
        self.assertEqual(result.status, ProductCompletionStatus.FAILED)
        self.assertEqual(result.blocking_codes, ("contradictory_persisted_identifiers",))

    def test_authority_diagnostic_is_preserved_without_failed_status(self):
        result = evaluate_product_completion(
            complete_facts(authority_diagnostic_code="h3_presentation_missing"),
            evaluated_at="fixed",
        )
        self.assertEqual(result.status, ProductCompletionStatus.NOT_READY)
        self.assertIn("h3_authority_invalid", result.blocking_codes)
        self.assertEqual(result.authority_diagnostic_code, "h3_presentation_missing")

    def test_delivery_checksum_rejection_is_not_ready(self):
        service = query_service_with_delivery_failure(
            AccessDeniedError("PDF checksum mismatch"),
        )
        result = service.product_completion("run-1", evaluated_at="fixed")
        self.assertEqual(result.status, ProductCompletionStatus.NOT_READY)
        self.assertIn("pdf_not_terminal", result.blocking_codes)

    def test_unexpected_delivery_exception_propagates(self):
        service = query_service_with_delivery_failure(RuntimeError("repository failure"))
        with self.assertRaisesRegex(RuntimeError, "repository failure"):
            service.product_completion("run-1", evaluated_at="fixed")


if __name__ == "__main__":
    unittest.main()
