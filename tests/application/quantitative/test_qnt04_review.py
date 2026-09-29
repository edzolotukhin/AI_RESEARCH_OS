"""Offline finality checks over immutable Quant statistical authorities."""

from dataclasses import replace
import unittest

from application.methods.quantitative.finding_authority import CanonicalQuantFindingSupportValidator
from application.methods.quantitative.insight_integrity import CanonicalQuantInsightValidator
from application.methods.quantitative.pin import (
    POST_ANALYSIS_VERSION, REVIEW_VERSION, resolve_review_pin,
)
from application.quantitative.deterministic_finding_proposals import DeterministicQuantitativeFindingProposalGenerator
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.report_composition import QuantitativeReportValidator
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.review import QuantitativeReviewService
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.insight import (
    QuantitativeFindingReference, QuantitativeInsight,
    QuantitativeInsightGenerationResult, QuantitativeInsightType,
)
from domain.quantitative.finding import QuantitativeClaimType
from domain.quantitative.report import (
    QuantitativeReport, QuantitativeReportCompositionResult,
    QuantitativeReportSection, QuantitativeReportSectionType,
    QuantitativeReportSupportReference,
)
from domain.quantitative.workflow import QuantitativeAnalysisManifest
from domain.reviews.review_verdict import ReviewVerdict
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
from infrastructure.persistence.postgresql.kernel_ownership import checkpoint_results
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative import test_qnt02_cmf_contracts as qnt02_fixture
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import result, comparison


class Qnt04ReviewTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()
        self.dataset = qnt02_fixture.Qnt02CmfContractsTests()._authority().dataset_version
        self.state_service = QuantitativeStateService(
            repository=InMemoryQuantitativeStateRepository(), digest_provider=self.digest)
        self.reviews = InMemoryReviewRepository()
        self.service = QuantitativeReviewService(
            state_service=self.state_service, digest_provider=self.digest,
            review_repository=self.reviews)
        self.project_id, self.run_id = self.dataset.project_id, self.dataset.run_id
        source = replace(result("share", "42"),
                         dataset_version_id=self.dataset.version_id,
                         dataset_fingerprint=self.dataset.dataset_fingerprint,
                         data_fingerprint=self.dataset.data_fingerprint,
                         codebook_fingerprint=self.dataset.codebook_fingerprint)
        self.finding_generation = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=CanonicalQuantFindingSupportValidator(
                digest_provider=self.digest, dataset=self.dataset, run_id=self.run_id),
            digest_provider=self.digest,
        ).generate(statistical_results=(source,))
        self.finding = self.finding_generation.accepted_findings[0]
        raw_insight = QuantitativeInsight(
            "insight-1", "Interpret the synthetic sample cautiously.",
            QuantitativeInsightType.LIMITATION,
            (QuantitativeFindingReference(self.finding.finding_id,
                                          self.finding.support_validation_fingerprint),),
            limitation_note="Synthetic sample only.")
        insight = CanonicalQuantInsightValidator(
            digest_provider=self.digest, require_canonical_authority=True,
        ).validate(raw_insight, findings={self.finding.finding_id: self.finding})
        self.insight_generation = QuantitativeInsightGenerationResult(
            "insight-generation-1", "finding-bundle", "offline-double", "qj", "prompt",
            (raw_insight,), (insight,), (), {}, {"accepted": 1}, "insight-generation-fp")
        ref = QuantitativeReportSupportReference(
            self.finding.finding_id, self.finding.support_validation_fingerprint)
        insight_ref = QuantitativeReportSupportReference(
            insight.insight_id, insight.validation_fingerprint)
        section = QuantitativeReportSection(
            "section-1", QuantitativeReportSectionType.KEY_FINDINGS,
            "Synthetic result", self.finding.text,
            (ref,), (), (self.finding.claim.display_value,),
            (source.result_id,), (), self.finding.claim.weighting_status,
            self.finding.claim.filter_definition, self.finding.claim.base_definition)
        limitation_section = QuantitativeReportSection(
            "section-2", QuantitativeReportSectionType.LIMITATIONS,
            "Synthetic limitations", insight.insight_text,
            (ref,), (insight_ref,), (), (source.result_id,), (),
            self.finding.claim.weighting_status,
            self.finding.claim.filter_definition, self.finding.claim.base_definition)
        report = QuantitativeReport(
            "report-1", "Synthetic report", (section, limitation_section),
            (ref,), (insight_ref,))
        accepted = QuantitativeReportValidator(digest_provider=self.digest).validate(
            report, findings={self.finding.finding_id: self.finding},
            insights={insight.insight_id: insight})
        self.composition = QuantitativeReportCompositionResult(
            "composition-1", "support-bundle", "offline-double", "qk", "prompt",
            report, accepted, (), {}, "composition-fp")
        self.manifest = QuantitativeAnalysisManifest(
            "manifest-1", self.dataset.version_id, ("stat-result",), (), (), "manifest-fp")
        self.state = {
            "dataset_record_id": "dataset-record", "dataset_version_id": self.dataset.version_id,
            "dataset_fingerprint": self.dataset.dataset_fingerprint,
            "analysis_manifest_record_id": "manifest-record",
            "finding_generation_record_id": "finding-record",
            "insight_generation_record_id": "insight-record",
            "report_composition_record_id": "report-record",
            "analysis_plan_fingerprint": "plan-fp",
            "weighting_authority_fingerprint": "unweighted-fp",
        }
        for record_id, value in (
            ("dataset-record", self.dataset), ("manifest-record", self.manifest),
            ("stat-result", source), ("finding-record", self.finding_generation),
            ("insight-record", self.insight_generation),
            ("report-record", self.composition),
        ):
            self._store(record_id, value)

    def _store(self, record_id, value):
        self.state_service.persist(value, record_id=record_id,
                                   project_id=self.project_id, run_id=self.run_id)

    def _replace_source(self, key, value, record_id):
        self._store(record_id, value)
        return {**self.state, key: record_id}

    def _bound_result(self, name, value, **kwargs):
        return replace(result(name, value, **kwargs),
                       dataset_version_id=self.dataset.version_id,
                       dataset_fingerprint=self.dataset.dataset_fingerprint,
                       data_fingerprint=self.dataset.data_fingerprint,
                       codebook_fingerprint=self.dataset.codebook_fingerprint)

    def _install_package(self, label, results, comparisons, selected_type):
        generated = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=CanonicalQuantFindingSupportValidator(
                digest_provider=self.digest, dataset=self.dataset, run_id=self.run_id),
            digest_provider=self.digest,
        ).generate(statistical_results=results, comparison_results=comparisons)
        chosen = next(item for item in generated.accepted_findings
                      if item.claim.claim_type is selected_type)
        raw_insight = QuantitativeInsight(
            f"insight-{label}", "Interpret the synthetic sample cautiously.",
            QuantitativeInsightType.LIMITATION,
            (QuantitativeFindingReference(chosen.finding_id,
                                          chosen.support_validation_fingerprint),),
            limitation_note="Synthetic sample only.")
        insight = CanonicalQuantInsightValidator(
            digest_provider=self.digest, require_canonical_authority=True,
        ).validate(raw_insight, findings={item.finding_id: item
                                          for item in generated.accepted_findings})
        insight_generation = replace(
            self.insight_generation, proposed_insights=(raw_insight,),
            accepted_insights=(insight,),
            generation_fingerprint=canonical_digest(
                {"insight": insight.validation_fingerprint, "label": label},
                digest_provider=self.digest))
        finding_ref = QuantitativeReportSupportReference(
            chosen.finding_id, chosen.support_validation_fingerprint)
        insight_ref = QuantitativeReportSupportReference(
            insight.insight_id, insight.validation_fingerprint)
        first = replace(self.composition.accepted_report.sections[0],
                        narrative=chosen.text, finding_refs=(finding_ref,),
                        referenced_display_values=(chosen.claim.display_value,),
                        authoritative_result_refs=tuple(ref.result_id
                                                        for ref in chosen.statistical_result_refs),
                        weighting_status=chosen.claim.weighting_status,
                        filter_definition=chosen.claim.filter_definition,
                        base_definition=chosen.claim.base_definition,
                        direction=chosen.claim.direction)
        second = replace(self.composition.accepted_report.sections[1],
                         finding_refs=(finding_ref,), insight_refs=(insight_ref,),
                         authoritative_result_refs=first.authoritative_result_refs,
                         weighting_status=chosen.claim.weighting_status,
                         filter_definition=chosen.claim.filter_definition,
                         base_definition=chosen.claim.base_definition)
        proposal = replace(self.composition.accepted_report,
                           report_id=f"report-{label}", sections=(first, second),
                           supporting_finding_refs=(finding_ref,),
                           supporting_insight_refs=(insight_ref,))
        accepted = QuantitativeReportValidator(digest_provider=self.digest).validate(
            proposal, findings={item.finding_id: item for item in generated.accepted_findings},
            insights={insight.insight_id: insight})
        composition = replace(self.composition, proposed_report=proposal,
                              accepted_report=accepted,
                              composition_fingerprint=canonical_digest(
                                  {"report": accepted.validation_fingerprint, "label": label},
                                  digest_provider=self.digest))
        state = dict(self.state)
        for key, value in (
            ("finding_generation_record_id", generated),
            ("insight_generation_record_id", insight_generation),
            ("report_composition_record_id", composition),
        ):
            record_id = f"{label}:{key}"
            self._store(record_id, value)
            state[key] = record_id
        result_ids = []
        for index, source in enumerate(results):
            record_id = f"{label}:result:{index}"
            self._store(record_id, source)
            result_ids.append(record_id)
        comparison_ids = []
        for index, source in enumerate(comparisons):
            record_id = f"{label}:comparison:{index}"
            self._store(record_id, source)
            comparison_ids.append(record_id)
        manifest = replace(self.manifest, statistical_result_record_ids=tuple(result_ids),
                           comparison_record_ids=tuple(comparison_ids),
                           fingerprint=f"manifest-{label}")
        manifest_id = f"{label}:manifest"
        self._store(manifest_id, manifest)
        state["analysis_manifest_record_id"] = manifest_id
        return state

    def test_approved_revision_binds_exact_sources_and_replay_is_idempotent(self):
        review, revision = self.service.review(project_id=self.project_id,
                                               run_id=self.run_id, state=self.state)
        self.assertEqual(review.verdict, ReviewVerdict.APPROVE)
        self.assertEqual(revision.review_id, review.review_id)
        self.assertEqual(revision.dataset_fingerprint, self.dataset.dataset_fingerprint)
        self.assertEqual(revision.finding_generation_fingerprint,
                         self.finding_generation.generation_fingerprint)
        self.assertEqual(revision.insight_generation_fingerprint,
                         self.insight_generation.generation_fingerprint)
        self.assertEqual(self.reviews.count_for_run(self.project_id, self.run_id), 1)
        self.assertEqual(self.service.review(project_id=self.project_id,
                                             run_id=self.run_id, state=self.state),
                         (review, revision))

    def test_non_significant_and_weighted_supported_packages_can_be_approved(self):
        weighted = self._bound_result(
            "weighted", "42", statistic_type="WEIGHTED_PERCENTAGE",
            weighting="WEIGHTED", weight_fingerprint="weights-fp")
        first = self._bound_result("group-a", "55")
        second = self._bound_result("group-b", "44")
        non_significant = comparison(first, second, significant=False)
        for label, results, comparisons, selected_type in (
            ("weighted", (weighted,), (), QuantitativeClaimType.DESCRIPTIVE_VALUE),
            ("non-significant", (first, second), (non_significant,),
             QuantitativeClaimType.NON_SIGNIFICANT_COMPARISON),
        ):
            with self.subTest(label=label):
                state = self._install_package(label, results, comparisons, selected_type)
                review, revision = self.service.review(
                    project_id=self.project_id, run_id=self.run_id, state=state)
                self.assertEqual(review.verdict, ReviewVerdict.APPROVE, review.issues)
                self.assertIsNotNone(revision)
                self.assertEqual(revision.analysis_manifest_fingerprint,
                                 f"manifest-{label}")

    def test_stale_dataset_and_report_narrative_require_revision(self):
        cases = (
            {**self.state, "dataset_fingerprint": "other-dataset"},
            self._replace_source("report_composition_record_id", replace(
                self.composition, accepted_report=replace(
                    self.composition.accepted_report,
                    sections=(replace(self.composition.accepted_report.sections[0],
                                      narrative="The result was 99%."),)),
            ), "tampered-report"),
        )
        for state in cases:
            with self.subTest(state=state):
                review, revision = self.service.review(
                    project_id=self.project_id, run_id=self.run_id, state=state)
                self.assertEqual(review.verdict, ReviewVerdict.REVISE)
                self.assertIsNone(revision)
                self.assertTrue(review.issues)

    def test_stale_insight_and_foreign_result_fail_closed(self):
        stale_insight = replace(self.insight_generation.accepted_insights[0],
                                insight_text="The result caused the outcome.")
        stale = self._replace_source("insight_generation_record_id", replace(
            self.insight_generation, accepted_insights=(stale_insight,)), "stale-insight")
        review, revision = self.service.review(project_id=self.project_id,
                                               run_id=self.run_id, state=stale)
        self.assertEqual(review.verdict, ReviewVerdict.REVISE)
        self.assertIsNone(revision)
        foreign = self._replace_source("analysis_manifest_record_id", replace(
            self.manifest, statistical_result_record_ids=("foreign-result",)),
            "foreign-manifest")
        self._store("foreign-result", replace(
            self.state_service.load("stat-result", project_id=self.project_id),
            dataset_fingerprint="foreign"))
        review, revision = self.service.review(project_id=self.project_id,
                                               run_id=self.run_id, state=foreign)
        self.assertEqual(review.verdict, ReviewVerdict.REVISE)
        self.assertIsNone(revision)

    def test_review_rejects_freshly_validated_unsupported_semantics(self):
        original = self.composition.accepted_report
        validator = QuantitativeReportValidator(digest_provider=self.digest)
        for narrative in (
            "The confidence interval is narrow.",
            "The estimate resulted in this outcome.",
            "The weighted estimate requires caution.",
        ):
            with self.subTest(narrative=narrative):
                changed_section = replace(original.sections[0], narrative=narrative,
                                          referenced_display_values=())
                proposal = replace(original, sections=(changed_section, *original.sections[1:]))
                accepted = validator.validate(
                    proposal, findings={self.finding.finding_id: self.finding},
                    insights={self.insight_generation.accepted_insights[0].insight_id:
                              self.insight_generation.accepted_insights[0]})
                self.assertNotEqual(accepted.validation_fingerprint,
                                    original.validation_fingerprint)
                record_id = f"report-{len(self.state_service.list_for_run(self.run_id, project_id=self.project_id))}"
                state = self._replace_source("report_composition_record_id",
                                             replace(self.composition, accepted_report=accepted,
                                                     composition_fingerprint=record_id),
                                             record_id)
                review, revision = self.service.review(
                    project_id=self.project_id, run_id=self.run_id, state=state)
                self.assertEqual(review.verdict, ReviewVerdict.REVISE)
                self.assertIsNone(revision)
                self.assertTrue(review.issues)

    def test_numeric_and_context_tampering_never_approves(self):
        section = self.composition.accepted_report.sections[0]
        report = self.composition.accepted_report
        cases = {
            "percentage": replace(section, narrative="The result was 99%."),
            "sample_n": replace(section, narrative="The sample N was 999."),
            "denominator": replace(section, base_definition="OTHER_BASE"),
            "mean": replace(section, narrative="The mean was 999."),
            "p_value": replace(section, narrative="p = 0.001."),
            "confidence_interval": replace(section, narrative="The 95% CI was narrow."),
            "false_significance": replace(section, narrative="Statistically significant."),
            "causality": replace(section, narrative="The result caused the outcome."),
            "weighting": replace(section, weighting_status="WEIGHTED"),
            "filter": replace(section, filter_definition="OTHER_FILTER"),
        }
        for label, changed in cases.items():
            with self.subTest(label=label):
                changed_report = replace(report, sections=(changed, *report.sections[1:]))
                state = self._replace_source(
                    "report_composition_record_id",
                    replace(self.composition, accepted_report=changed_report,
                            composition_fingerprint=f"tampered-{label}"),
                    f"tampered-{label}")
                review, revision = self.service.review(
                    project_id=self.project_id, run_id=self.run_id, state=state)
                self.assertEqual(review.verdict, ReviewVerdict.REVISE)
                self.assertIsNone(revision)
                self.assertTrue(review.issues)

    def test_cross_run_and_missing_authority_fail_closed(self):
        self.state_service.persist(
            self.composition, record_id="another-run-report",
            project_id=self.project_id, run_id="another-run")
        with self.assertRaises(ValueError):
            self.service.review(project_id=self.project_id, run_id=self.run_id,
                                state={**self.state,
                                       "report_composition_record_id": "another-run-report"})
        with self.assertRaises(ValueError):
            self.service.review(project_id=self.project_id, run_id=self.run_id,
                                state={**self.state,
                                       "analysis_manifest_record_id": "missing-manifest"})
        self.assertEqual(self.reviews.count_for_run(self.project_id, self.run_id), 0)

    def test_review_pin_is_protected_and_legacy_run_is_unchanged(self):
        self.assertFalse(resolve_review_pin(None, method_pin={"method": "quant"},
                                            post_analysis_pin=POST_ANALYSIS_VERSION))
        self.assertTrue(resolve_review_pin(REVIEW_VERSION, method_pin={"method": "quant"},
                                           post_analysis_pin=POST_ANALYSIS_VERSION))
        with self.assertRaises(ValueError):
            resolve_review_pin(REVIEW_VERSION, method_pin={"method": "quant"},
                               post_analysis_pin=None)
        self.assertEqual(checkpoint_results({"_cmf_quant_review_v1": REVIEW_VERSION},
                                            {"_cmf_quant_review_v1": "forged"})[
                                                "_cmf_quant_review_v1"], REVIEW_VERSION)


if __name__ == "__main__":
    unittest.main()
