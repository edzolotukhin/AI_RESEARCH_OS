from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from application.config import ApplicationConfig
from application.deliverables.editorial_delivery import (
    EditorialDeliveryError,
    load_approved_editorial_delivery,
    render_editorial_markdown,
    render_coverage_limitation,
)
from application.report.editorial_contract import (
    CoverageLimitation, CoverageStatus, EvidenceRequirementLabel,
    ImpactLabel, MissingDimension,
)
from api.mappers.report_mappers import report_to_response
from application.deliverables.service import ProjectDeliverablesService
from domain.reviews.review_verdict import ReviewVerdict
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
import tests.application.review.test_presentation_review_lifecycle as review_fixtures


class EditorialDeliveryTests(unittest.TestCase):
    def setUp(self):
        fixture = review_fixtures.PresentationReviewLifecycleTests()
        _, _, review_service, reviews, context, reports, claims = fixture.fixture()
        summary = review_service.review_for_context(context)
        self.report = reports.get_by_id(summary.report_id)
        self.review = reviews.get_by_id(summary.review_id)
        self.claims = tuple(claims.list_for_report(self.report.id, self.report.revision_number))

    def load(self, **values):
        return load_approved_editorial_delivery(
            report=values.get("report", self.report),
            review=values.get("review", self.review),
            claims=values.get("claims", self.claims),
        )

    def test_exact_approved_presentation_projects_deterministically(self):
        first = self.load()
        second = self.load()
        self.assertEqual(first, second)
        self.assertEqual(self.report.id, first.provenance.report_id)
        self.assertEqual(self.report.workflow_run_id, first.provenance.report_workflow_run_id)
        self.assertTrue(first.document.executive_summary)
        self.assertTrue(first.document.sections)
        self.assertTrue(first.document.references)
        self.assertEqual(
            render_editorial_markdown(first.document),
            render_editorial_markdown(second.document),
        )

    def test_non_approve_and_wrong_review_identity_fail_closed(self):
        for review in (
            replace(self.review, verdict=ReviewVerdict.REVISE),
            replace(self.review, report_id="foreign-report"),
        ):
            with self.subTest(review=review), self.assertRaises(EditorialDeliveryError):
                self.load(review=review)

    def test_digest_revision_and_lineage_mismatches_fail_closed(self):
        mutations = (
            {"approved_revision_number": 99},
            {"approved_authority_digest": "0" * 64},
            {"approved_presentation_digest": "0" * 64},
            {"claim_set_digest": "0" * 64},
            {"coverage_contract_digest": "0" * 64},
        )
        for mutation in mutations:
            review = replace(self.review, metadata={**self.review.metadata, **mutation})
            with self.subTest(mutation=mutation), self.assertRaises(EditorialDeliveryError):
                self.load(review=review)
        foreign = replace(self.claims[0], source_workflow_run_id="foreign-run")
        with self.assertRaises(EditorialDeliveryError):
            self.load(claims=(foreign, *self.claims[1:]))

    def test_markdown_preserves_wording_and_citation_keys_without_internal_ids(self):
        delivery = self.load()
        markdown = render_editorial_markdown(delivery.document)
        for paragraph in delivery.document.executive_summary:
            self.assertIn(paragraph.text, markdown)
        for reference in delivery.document.references:
            self.assertIn(f"[{reference.display_key}]", markdown)
        self.assertNotIn("claim_", markdown)
        self.assertNotIn("fact_", markdown)
        self.assertNotIn("period_", markdown)
        self.assertNotIn("Unsupported ResearchQuestions", markdown)

    def test_new_generation_default_and_explicit_legacy_rollback_selector(self):
        self.assertEqual("desk_h3_structural_claim_v1", ApplicationConfig().desk_report_contract_version)
        with patch.dict("os.environ", {"DESK_REPORT_CONTRACT_VERSION": "desk_report_claim_v1"}):
            self.assertEqual(
                "desk_report_claim_v1",
                ApplicationConfig.from_env().desk_report_contract_version,
            )

    def test_approved_artifact_is_exact_and_idempotent(self):
        delivery = self.load()
        service = object.__new__(ProjectDeliverablesService)
        service.artifacts = InMemoryArtifactRepository()
        first = service._persist_editorial_artifact(self.report, delivery)
        second = service._persist_editorial_artifact(self.report, delivery)
        self.assertEqual(first.id, second.id)
        self.assertEqual("approved", first.status)
        self.assertEqual(delivery.provenance, first.approved_delivery_provenance)
        self.assertEqual(1, len(service.artifacts.list_for_run(self.report.workflow_run_id)))

    def test_api_projection_uses_canonical_delivery_and_invalid_editorial_never_falls_back(self):
        delivery = self.load()
        response = report_to_response(self.report, delivery=delivery)
        self.assertTrue(response.delivery_available)
        self.assertEqual(delivery.document.title, response.title)
        self.assertEqual(delivery.provenance.presentation_digest, response.presentation_digest)
        self.assertEqual(
            "\n\n".join(item.text for item in delivery.document.executive_summary),
            response.executive_summary,
        )
        unavailable = report_to_response(self.report)
        self.assertFalse(unavailable.delivery_available)
        self.assertEqual([], unavailable.sections)
        self.assertEqual("", unavailable.executive_summary)

    def test_typed_limitation_is_natural_and_contains_no_internal_references(self):
        item = CoverageLimitation(
            limitation_id="limitation-1", topic_ref="rq_internal",
            supported_claim_refs=("claim_internal",), supported_period_refs=(),
            missing_dimensions=(MissingDimension.PERIOD, MissingDimension.GEOGRAPHY),
            missing_periods=("period_internal",),
            coverage_status=CoverageStatus.PARTIAL,
            impact_label=ImpactLabel.LIMITS_TREND_INFERENCE,
            evidence_requirement_labels=(EvidenceRequirementLabel.ADDITIONAL_PERIODS,),
        )
        rendered = render_coverage_limitation(item)
        self.assertIn("часового охоплення", rendered)
        self.assertIn("географічного охоплення", rendered)
        for internal in ("rq_internal", "claim_internal", "period_internal", "PARTIAL"):
            self.assertNotIn(internal, rendered)


if __name__ == "__main__":
    unittest.main()
