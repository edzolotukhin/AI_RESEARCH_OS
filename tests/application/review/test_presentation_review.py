from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from application.report.coverage_contract import ReportCoverageContract
from application.report.presentation_persistence import (
    attach_editorial_envelope,
    presentation_report_digest,
    report_claims_authority_digest,
)
from application.review.presentation_review import (
    MAX_FULL_REPORT_LIFECYCLE_CALLS,
    MAX_SEMANTIC_REVIEW_CALLS_PER_PASS,
    PresentationReviewError,
    PresentationTargetType,
    build_presentation_review_input,
    deterministic_presentation_issues,
    resolve_semantic_presentation_issues,
)
from domain.reports.report import Report
from domain.ai.llm_response import LLMResponse
from application.review.exceptions import ReviewConfigurationError
from infrastructure.review.llm_review_engine import LlmReviewEngine
import tests.application.report.test_editorial_composer as editorial_fixtures


class PresentationReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = editorial_fixtures.EditorialComposerTests()
        fixture.setUp()
        self.claims = fixture.claims
        result, _ = fixture.compose(fixture.valid)
        presentation = replace(
            result.report,
            authority_digest=report_claims_authority_digest(self.claims),
            source_report_id=result.report.report_id,
        )
        diagnostics = {
            **result.diagnostics,
            "authority_digest": presentation.authority_digest,
            "presentation_digest": presentation_report_digest(presentation),
        }
        registry = {
            item.citation_id: {
                "source_id": item.source_id, "title": item.title,
                "canonical_url": item.canonical_url,
            }
            for item in presentation.citations
        }
        self.report = Report(
            id=presentation.report_id, project_id="project", workflow_run_id="run",
            research_design_id="design", title=presentation.title, language="uk",
            sections=(), executive_summary="", limitations=(), created_at="now",
            generation_method="claim-first:test", finding_refs=(), insight_refs=(),
            evidence_refs=(), citation_registry=registry, deduplication_key="report",
            revision_number=presentation.revision_number,
            metadata=attach_editorial_envelope(
                {"structured_claim_contract": "desk_report_claim_v1"},
                presentation=presentation, claims=self.claims, diagnostics=diagnostics,
            ),
        )
        rqs = tuple(sorted({rq for claim in self.claims for rq in claim.research_question_ids}))
        self.coverage = ReportCoverageContract("complete", rqs, ())

    def build(self):
        return build_presentation_review_input(
            report=self.report, claims=self.claims, coverage_contract=self.coverage,
        )

    def test_exact_input_maps_paragraphs_claims_and_support(self) -> None:
        value = self.build()
        self.assertEqual(self.report.id, value.report_id)
        for paragraph_id, refs in value.paragraph_claim_refs.items():
            self.assertTrue(paragraph_id)
            self.assertTrue(set(refs) <= set(value.claim_support))
        for claim in self.claims:
            self.assertEqual(claim.finding_ids, value.claim_support[claim.claim_id]["finding_ids"])
            self.assertEqual(claim.evidence_ids, value.claim_support[claim.claim_id]["evidence_ids"])

    def test_exact_target_catalog_has_no_fallback(self) -> None:
        value = self.build()
        catalog = value.target_catalog()
        self.assertIn((PresentationTargetType.REPORT.value, self.report.id), catalog)
        self.assertNotIn((PresentationTargetType.PARAGRAPH.value, "foreign"), catalog)
        with self.assertRaises(PresentationReviewError):
            resolve_semantic_presentation_issues({"issues": [{
                "target_type": "PARAGRAPH", "target_ref": "foreign",
                "issue_type": "clarity", "severity": "major", "message": "x",
                "revision_instruction": "y",
            }]}, review_input=value)

    def test_provider_factual_issue_types_are_rejected(self) -> None:
        value = self.build()
        paragraph = next(iter(value.paragraph_claim_refs))
        for issue_type in ("unsupported_claim", "missing_citation"):
            with self.subTest(issue_type=issue_type), self.assertRaises(PresentationReviewError):
                resolve_semantic_presentation_issues({"issues": [{
                    "target_type": "PARAGRAPH", "target_ref": paragraph,
                    "issue_type": issue_type, "severity": "major", "message": "x",
                    "revision_instruction": "y",
                }]}, review_input=value)

    def test_valid_semantic_target_resolves_exact_claims(self) -> None:
        value = self.build()
        paragraph, claims = next(iter(value.paragraph_claim_refs.items()))
        issues = resolve_semantic_presentation_issues({"issues": [{
            "target_type": "PARAGRAPH", "target_ref": paragraph,
            "issue_type": "clarity", "severity": "minor", "message": "Уточнити",
            "revision_instruction": "Спростити речення",
        }]}, review_input=value)
        self.assertEqual(claims, issues[0].claim_refs)
        self.assertEqual(paragraph, issues[0].metadata["target_ref"])

    def test_valid_citations_are_recognized_deterministically(self) -> None:
        self.assertEqual((), deterministic_presentation_issues(self.build()))

    def test_missing_and_orphan_citations_are_detected(self) -> None:
        value = self.build()
        presentation = value.presentation
        section = presentation.sections[0]
        paragraph = section.paragraphs[0]
        without = replace(paragraph, citation_refs=())
        broken = replace(presentation, sections=(replace(section, paragraphs=(without, *section.paragraphs[1:])), *presentation.sections[1:]))
        report = self._replace_presentation(broken)
        issues = deterministic_presentation_issues(build_presentation_review_input(report=report, claims=self.claims, coverage_contract=self.coverage))
        codes = {item.metadata["code"] for item in issues}
        self.assertIn("missing_required_citation", codes)
        orphan_ref = presentation.citations[0].citation_ref
        def strip_ref(item):
            return replace(item, citation_refs=tuple(ref for ref in item.citation_refs if ref != orphan_ref))
        orphaned = replace(
            presentation,
            executive_summary=replace(
                presentation.executive_summary,
                paragraphs=tuple(strip_ref(item) for item in presentation.executive_summary.paragraphs),
            ),
            sections=tuple(
                replace(section, paragraphs=tuple(strip_ref(item) for item in section.paragraphs))
                for section in presentation.sections
            ),
        )
        orphan_issues = deterministic_presentation_issues(build_presentation_review_input(report=self._replace_presentation(orphaned), claims=self.claims, coverage_contract=self.coverage))
        self.assertIn("orphan_citation", {item.metadata["code"] for item in orphan_issues})

    def test_citation_to_unrelated_claim_fails(self) -> None:
        value = self.build()
        presentation = value.presentation
        citation = presentation.citations[0]
        other = next(claim.claim_id for claim in self.claims if claim.claim_id != citation.claim_ref)
        mutated = replace(presentation, citations=(replace(citation, claim_ref=other), *presentation.citations[1:]))
        report = self._replace_presentation(mutated)
        with self.assertRaises(PresentationReviewError):
            build_presentation_review_input(report=report, claims=self.claims, coverage_contract=self.coverage)

    def test_canonical_display_key_mismatch_fails_before_provider(self) -> None:
        presentation = self.build().presentation
        citation = presentation.citations[0]
        mutated = replace(presentation, citations=(replace(citation, display_key="wrong"), *presentation.citations[1:]))
        with self.assertRaises(PresentationReviewError):
            build_presentation_review_input(report=self._replace_presentation(mutated), claims=self.claims, coverage_contract=self.coverage)

    def test_foreign_claim_fails_before_provider(self) -> None:
        presentation = self.build().presentation
        section = presentation.sections[0]
        paragraph = section.paragraphs[0]
        mutated = replace(paragraph, claim_refs=(*paragraph.claim_refs, "foreign"))
        presentation = replace(presentation, sections=(replace(section, paragraphs=(mutated, *section.paragraphs[1:])), *presentation.sections[1:]))
        with self.assertRaises(PresentationReviewError):
            build_presentation_review_input(report=self._replace_presentation(presentation), claims=self.claims, coverage_contract=self.coverage)

    def test_authority_digest_is_identity_neutral_for_cloned_claims(self) -> None:
        cloned = tuple(replace(item, claim_id=f"new-{index}") for index, item in enumerate(self.claims))
        self.assertEqual(report_claims_authority_digest(self.claims), report_claims_authority_digest(cloned))

    def test_call_budget_constants(self) -> None:
        self.assertEqual(2, MAX_SEMANTIC_REVIEW_CALLS_PER_PASS)
        self.assertEqual(10, MAX_FULL_REPORT_LIFECYCLE_CALLS)

    def test_limited_coverage_requires_typed_limitation_not_invented_facts(self) -> None:
        required = self.coverage.required_rq_ids[:1]
        limited = ReportCoverageContract("limited", required, ("rq-gap",))
        value = build_presentation_review_input(report=self.report, claims=self.claims, coverage_contract=limited)
        self.assertIn("required_limitation_missing", {item.metadata["code"] for item in deterministic_presentation_issues(value)})
        limitation = replace(value.presentation.limitations[0], topic_ref="rq-gap")
        presentation = replace(value.presentation, limitations=(limitation,))
        repaired = build_presentation_review_input(report=self._replace_presentation(presentation), claims=self.claims, coverage_contract=limited)
        self.assertNotIn("required_limitation_missing", {item.metadata["code"] for item in deterministic_presentation_issues(repaired)})

    def test_whole_report_semantic_review_uses_one_call_when_valid(self) -> None:
        llm = MagicMock()
        llm.generate.return_value = LLMResponse(content='{"issues":[]}')
        engine = LlmReviewEngine(llm_client=llm)
        self.assertEqual((), engine.review_presentation(self.build()))
        self.assertEqual(1, llm.generate.call_count)
        self.assertEqual(1, engine.llm_call_count)

    def test_invalid_target_gets_one_repair_and_no_third_call(self) -> None:
        llm = MagicMock()
        invalid = '{"issues":[{"target_type":"PARAGRAPH","target_ref":"foreign","issue_type":"clarity","severity":"major","message":"x","revision_instruction":"y"}]}'
        llm.generate.side_effect = [LLMResponse(content=invalid), LLMResponse(content='{"issues":[]}')]
        engine = LlmReviewEngine(llm_client=llm)
        self.assertEqual((), engine.review_presentation(self.build()))
        self.assertEqual(2, llm.generate.call_count)
        self.assertEqual(2, engine.llm_call_count)

    def test_two_invalid_semantic_outputs_fail_closed_at_two_calls(self) -> None:
        llm = MagicMock()
        llm.generate.return_value = LLMResponse(content='{"issues":[{"target_type":"REPORT","target_ref":"foreign","issue_type":"clarity","severity":"major","message":"x","revision_instruction":"y"}]}')
        engine = LlmReviewEngine(llm_client=llm)
        with self.assertRaises(ReviewConfigurationError):
            engine.review_presentation(self.build())
        self.assertEqual(2, llm.generate.call_count)
        self.assertEqual(2, engine.llm_call_count)

    def _replace_presentation(self, presentation):
        diagnostics = copy.deepcopy(self.report.metadata["editorial"]["diagnostics"])
        diagnostics["presentation_digest"] = presentation_report_digest(presentation)
        metadata = attach_editorial_envelope(
            {"structured_claim_contract": "desk_report_claim_v1"},
            presentation=presentation, claims=self.claims, diagnostics=diagnostics,
        )
        return replace(self.report, metadata=metadata)


if __name__ == "__main__":
    unittest.main()
