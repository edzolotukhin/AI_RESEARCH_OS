from __future__ import annotations

import copy
import unittest

from application.ports.review_ports import ReviewIssueCandidate
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION
from application.review.review_service import ReviewService
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
import tests.application.report.test_presentation_integration_3a as presentation_3a


class _CitedEditorialProvider:
    def __init__(self, *, fail_revision: bool = False) -> None:
        self.requests = []
        self.fail_revision = fail_revision

    def generate(self, request):
        self.requests.append(copy.deepcopy(request))
        if self.fail_revision and "revision" in request:
            return {"invalid": True}
        claim = request["claims"][0]
        segments = [
            {"type": "TEXT", "text": "Підтверджений показник становить "},
            {"type": "FACT_REF", "claim_ref": claim["claim_ref"], "fact_ref": claim["fact_refs"][0], "variant": "value_with_unit"},
            {"type": "CITATION_REF", "claim_ref": claim["claim_ref"], "citation_ref": claim["citation_refs"][0]},
            {"type": "TEXT", "text": "."},
        ]
        paragraph = {"paragraph_id": "paragraph-1", "group_refs": [], "segments": segments}
        return {
            "contract_version": EDITORIAL_CONTRACT_VERSION,
            "report_title": "Заголовок",
            "executive_summary": [paragraph],
            "sections": [{
                "section_id": "section-1", "title": "Підтверджені результати",
                "purpose": "Виклад результатів",
                "paragraphs": [{**paragraph, "paragraph_id": "paragraph-2"}],
            }],
        }


class _PresentationEngine:
    method_name = "test-presentation"

    def __init__(self, *, revise_once=False, always_revise=False) -> None:
        self.revise_once = revise_once
        self.always_revise = always_revise
        self.calls = 0
        self.llm_call_count = 0

    def review_presentation(self, value):
        self.calls += 1
        self.llm_call_count = 1
        if self.always_revise or (self.revise_once and self.calls == 1):
            paragraph = next(iter(value.paragraph_claim_refs))
            target = value.target_catalog()[("PARAGRAPH", paragraph)]
            return (ReviewIssueCandidate(
                issue_type="structure_issue", severity="major",
                message="Уточнити виклад", report_section_id=target.section_id,
                claim_refs=target.claim_refs, report_revision=value.revision_number,
                suggested_action="Спростити речення",
                metadata={
                    "contract_version": EDITORIAL_CONTRACT_VERSION,
                    "semantic_issue_type": "clarity",
                    "target_type": "PARAGRAPH", "target_ref": paragraph,
                },
            ),)
        return ()

    def review_report(self, value):
        raise AssertionError("legacy Review path must not be used")


class PresentationReviewLifecycleTests(unittest.TestCase):
    def fixture(self, *, revise_once=False, always_revise=False, fail_revision=False):
        provider = _CitedEditorialProvider(fail_revision=fail_revision)
        base = presentation_3a.PresentationRuntimeIntegrationTests()
        service, context, reports, claims, artifacts, _ = base._fixture(provider=provider)
        service.write_for_context(context)
        review_repo = InMemoryReviewRepository()
        engine = _PresentationEngine(revise_once=revise_once, always_revise=always_revise)
        review = ReviewService(
            semantic_review_engine=engine,
            finding_repository=service._finding_repository,
            insight_repository=service._insight_repository,
            evidence_repository=service._evidence_repository,
            report_repository=reports, report_claim_repository=claims,
            artifact_repository=artifacts, review_repository=review_repo,
            report_service=service, max_revision_attempts=5,
        )
        return provider, service, review, review_repo, context, reports, claims

    def test_initial_approve_uses_exact_presentation_without_artifact(self):
        provider, _, review, reviews, context, reports, _ = self.fixture()
        summary = review.review_for_context(context)
        self.assertEqual("approve", summary.verdict)
        self.assertIsNone(summary.artifact_id)
        self.assertEqual(1, len(reports.list_for_project(context.project.id)))
        stored = reviews.get_by_id(summary.review_id)
        self.assertEqual(summary.report_id, stored.metadata["reviewed_report_id"])
        self.assertEqual(1, stored.metadata["semantic_provider_call_count"])
        self.assertEqual(1, len(provider.requests))

    def test_revise_once_persists_new_identity_and_approves_exact_revision(self):
        provider, _, review, reviews, context, reports, claims = self.fixture(revise_once=True)
        initial = reports.list_for_project(context.project.id)[0]
        old_claims = tuple(claims.list_for_report(initial.id, initial.revision_number))
        summary = review.review_for_context(context)
        self.assertEqual("approve", summary.verdict)
        self.assertEqual(1, summary.revision_count)
        revised = reports.get_by_id(summary.report_id)
        self.assertNotEqual(initial.id, revised.id)
        self.assertEqual(initial.revision_number + 1, revised.revision_number)
        self.assertEqual(initial.id, revised.previous_report_id)
        new_claims = tuple(claims.list_for_report(revised.id, revised.revision_number))
        from application.report.presentation_persistence import report_claims_authority_digest
        self.assertEqual(report_claims_authority_digest(old_claims), report_claims_authority_digest(new_claims))
        final_review = reviews.get_by_id(summary.review_id)
        self.assertEqual(revised.id, final_review.metadata["reviewed_report_id"])
        self.assertEqual(revised.revision_number, final_review.metadata["reviewed_revision_number"])
        self.assertEqual(2, len(provider.requests))
        self.assertIn("revision", provider.requests[1])

    def test_revision_composer_failure_creates_no_partial_revision(self):
        _, _, review, _, context, reports, _ = self.fixture(revise_once=True, fail_revision=True)
        with self.assertRaises(Exception):
            review.review_for_context(context)
        self.assertEqual(1, len(reports.list_for_project(context.project.id)))

    def test_second_revise_is_terminal_and_never_creates_revision_three(self):
        provider, _, review, _, context, reports, _ = self.fixture(always_revise=True)
        with self.assertRaises(Exception):
            review.review_for_context(context)
        persisted = reports.list_for_project(context.project.id)
        self.assertEqual(2, len(persisted))
        self.assertEqual([1, 2], sorted(item.revision_number for item in persisted))
        self.assertEqual(2, len(provider.requests))


if __name__ == "__main__":
    unittest.main()
