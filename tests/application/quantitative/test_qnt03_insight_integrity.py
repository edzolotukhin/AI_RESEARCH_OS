"""Provider-free adversarial checks for the new CMF Quant interpretation gate."""

import unittest
from dataclasses import replace

from application.methods.quantitative.insight_integrity import CanonicalQuantInsightValidator
from application.quantitative.insight_synthesis import QuantitativeInsightSynthesisService
from application.quantitative.deterministic_finding_proposals import DeterministicQuantitativeFindingProposalGenerator
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.methods.quantitative.finding_authority import CanonicalQuantFindingSupportValidator
from domain.quantitative.finding import QuantitativeClaimType
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import result, comparison
from tests.application.quantitative.test_property_qj_quantitative_insight_synthesis import (
    PropertyQJQuantitativeInsightSynthesisTests,
    insight_proposal,
)
from tests.application.quantitative.test_qnt02_cmf_contracts import Qnt02CmfContractsTests


class _Generator:
    identity = "qnt03-offline-test-double"

    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class QNT03InsightIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PropertyQJQuantitativeInsightSynthesisTests()
        self.fixture.setUp()
        self.finding = self.fixture.supported_single(
            result("share", "42"),
            QuantitativeClaimType.DESCRIPTIVE_VALUE,
            finding_id="share-finding",
        )

    def generate(self, text, *, finding=None, values=("42.0",), limitation="Observed sample only."):
        bound = finding or self.finding
        proposal = insight_proposal("LIMITATION", text, (bound,), values=values,
                                    limitation=limitation)
        service = QuantitativeInsightSynthesisService(
            generator=_Generator({"proposals": [proposal]}),
            validator=CanonicalQuantInsightValidator(digest_provider=Sha256DigestProvider()),
            digest_provider=Sha256DigestProvider(),
        )
        return service.generate(findings=(bound,))

    def test_valid_interpretation_is_accepted(self):
        generated = self.generate("The observed 42.0% should be interpreted cautiously.")
        self.assertEqual(generated.acceptance_summary["accepted"], 1)

    def test_unbound_numbers_and_semantics_fail_closed(self):
        cases = (
            ("Invented 73.0% from these results.", "percentage is not a bound"),
            ("Observed 43.0% instead.", "percentage is not a bound"),
            ("N=999 supports the result.", "sample/base count"),
            ("The denominator=999 is reliable.", "sample/base count"),
            ("The p=0.01 confirms this.", "p-value"),
            ("The confidence interval is narrow.", "confidence intervals"),
            ("This is a significant difference.", "significance"),
            ("The result caused this outcome.", "causal"),
            ("The weighted estimate is 42.0%.", "weighted interpretation"),
        )
        for text, reason in cases:
            with self.subTest(text=text):
                generated = self.generate(text)
                self.assertEqual(generated.acceptance_summary["accepted"], 0)
                self.assertIn(reason, generated.rejected_insights[0].reason)

    def test_malformed_output_and_provider_failure_are_operational_errors(self):
        digest = Sha256DigestProvider()
        for response in ({"proposals": "invalid"}, RuntimeError("provider offline")):
            service = QuantitativeInsightSynthesisService(
                generator=_Generator(response),
                validator=CanonicalQuantInsightValidator(digest_provider=digest),
                digest_provider=digest,
            )
            with self.assertRaises(Exception):
                service.generate(findings=(self.finding,))

    def test_non_significant_comparison_may_be_described_without_upgrade(self):
        first = result("a", "55")
        second = result("b", "44")
        digest = Sha256DigestProvider()
        generated = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=QuantitativeFindingSupportValidator(digest_provider=digest),
            digest_provider=digest,
        ).generate(statistical_results=(first, second),
                   comparison_results=(comparison(first, second, significant=False),))
        bound = next(item for item in generated.accepted_findings
                     if item.comparison_result_refs)
        safe = self.generate("The observed difference was not statistically significant.",
                             finding=bound, values=())
        self.assertEqual(safe.acceptance_summary["accepted"], 1)
        unsafe = self.generate("The difference was statistically significant.",
                               finding=bound, values=())
        self.assertEqual(unsafe.acceptance_summary["accepted"], 0)

    def test_weighted_finding_cannot_be_presented_as_unweighted(self):
        weighted = self.fixture.supported_single(
            result("weighted", "42", statistic_type="WEIGHTED_PERCENTAGE",
                   weighting="WEIGHTED", weight_fingerprint="weights"),
            QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="weighted-finding",
        )
        generated = self.generate("The unweighted result was 42.0%.", finding=weighted)
        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertIn("unweighted interpretation", generated.rejected_insights[0].reason)

    def test_stale_finding_reference_is_not_promoted(self):
        proposal = insight_proposal("LIMITATION", "Interpret cautiously.",
                                    (self.finding,), values=(), limitation="Observed sample only.")
        proposal["supporting_finding_ids"] = ["stale-finding-id"]
        digest = Sha256DigestProvider()
        service = QuantitativeInsightSynthesisService(
            generator=_Generator({"proposals": [proposal]}),
            validator=CanonicalQuantInsightValidator(digest_provider=digest),
            digest_provider=digest,
        )
        generated = service.generate(findings=(self.finding,))
        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertIn("missing", generated.rejected_insights[0].reason)

    def test_canonical_p_value_and_source_n_are_exactly_bounded(self):
        dataset = Qnt02CmfContractsTests()._authority().dataset_version
        def bound(source):
            return replace(source, dataset_version_id=dataset.version_id,
                           dataset_fingerprint=dataset.dataset_fingerprint,
                           data_fingerprint=dataset.data_fingerprint,
                           codebook_fingerprint=dataset.codebook_fingerprint)
        first, second = bound(result("a", "55")), bound(result("b", "44"))
        compared = comparison(first, second)
        digest = Sha256DigestProvider()
        generated = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=CanonicalQuantFindingSupportValidator(
                digest_provider=digest, dataset=dataset, run_id=dataset.run_id,
            ), digest_provider=digest,
        ).generate(statistical_results=(first, second), comparison_results=(compared,))
        finding = next(item for item in generated.accepted_findings
                       if item.comparison_result_refs)
        self.assertIsNotNone(finding.canonical_authority)
        def assess(text, values):
            proposal = insight_proposal("LIMITATION", text, (finding,), values=values,
                                        limitation="Observed sample only.")
            return QuantitativeInsightSynthesisService(
                generator=_Generator({"proposals": [proposal]}),
                validator=CanonicalQuantInsightValidator(
                    digest_provider=digest, require_canonical_authority=True,
                ), digest_provider=digest,
            ).generate(findings=(finding,))
        self.assertEqual(assess("The comparison reports p=0.01.", ("0.01",))
                         .acceptance_summary["accepted"], 1)
        self.assertEqual(assess("The comparison reports p=0.02.", ("0.02",))
                         .acceptance_summary["accepted"], 0)
        self.assertEqual(assess(f"Source N={dataset.row_count}.", (str(dataset.row_count),))
                         .acceptance_summary["accepted"], 1)
        self.assertEqual(assess(f"Source N={dataset.row_count + 1}.",
                                (str(dataset.row_count + 1),))
                         .acceptance_summary["accepted"], 0)


if __name__ == "__main__":
    unittest.main()
