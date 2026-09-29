"""Offline checks for the CMF Quant provider-free Finding selector."""

import unittest
from dataclasses import replace

from application.quantitative.deterministic_finding_proposals import (
    DeterministicQuantitativeFindingProposalGenerator,
)
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.methods.quantitative.finding_authority import CanonicalQuantFindingSupportValidator
from application.methods.quantitative.pin import POST_ANALYSIS_VERSION, resolve_post_analysis_pin
from domain.quantitative.finding import QuantitativeSupportStatus
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from infrastructure.persistence.postgresql.kernel_ownership import checkpoint_results
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import result
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import comparison
from tests.application.quantitative.test_qnt02_cmf_contracts import Qnt02CmfContractsTests


class QNT03DeterministicFindingTests(unittest.TestCase):
    def setUp(self):
        digest = Sha256DigestProvider()
        self.service = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=QuantitativeFindingSupportValidator(digest_provider=digest),
            digest_provider=digest,
        )

    def test_exact_values_and_result_provenance_are_application_bound(self):
        percentage = result("share", "42.345")
        weighted = result("weighted", "17.25", statistic_type="WEIGHTED_PERCENTAGE",
                          weighting="WEIGHTED", weight_fingerprint="weight-fp")
        mean = result("mean", "4.75", statistic_type="NUMERIC_MEAN")
        authority = (percentage, weighted, mean)
        calls = []
        generated = self.service.generate(
            statistical_results=authority,
            before_dispatch=lambda: calls.append("external-dispatch"),
        )
        # This service's callback remains available for legacy provider calls.
        self.assertEqual(calls, ["external-dispatch"])
        self.assertEqual(generated.acceptance_summary, {
            "proposed": 3, "parsed": 3, "accepted": 3, "rejected": 0,
        })
        by_result = {item.statistical_result_refs[0].result_id: item
                     for item in generated.accepted_findings}
        self.assertEqual(set(by_result), {item.result_id for item in authority})
        for item in authority:
            finding = by_result[item.result_id]
            self.assertEqual(finding.claim.value, item.value)
            self.assertEqual(finding.statistical_result_refs[0].reproducibility_fingerprint,
                             item.reproducibility_fingerprint)
            self.assertEqual(finding.support_validation_status, QuantitativeSupportStatus.SUPPORTED)
        self.assertEqual(by_result["weighted"].claim.weighting_status, "WEIGHTED")
        self.assertEqual(by_result["weighted"].claim.weight_set_fingerprint, "weight-fp")
        repeated = self.service.generate(statistical_results=authority)
        self.assertEqual(repeated.generation_fingerprint, generated.generation_fingerprint)

    def test_ineligible_result_cannot_become_accepted(self):
        ineligible = replace(result("hidden", "10"), presentation_eligible=False)
        generated = self.service.generate(statistical_results=(ineligible,))
        self.assertEqual(generated.accepted_findings, ())
        self.assertEqual(generated.generation_metadata["abstention_reason"],
                         "NO_PRESENTATION_ELIGIBLE_QH_SUPPORT")

    def test_canonical_authority_binds_dataset_run_source_n_and_checksum(self):
        dataset = Qnt02CmfContractsTests()._authority().dataset_version
        source = replace(
            result("share", "42"), dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            data_fingerprint=dataset.data_fingerprint,
            codebook_fingerprint=dataset.codebook_fingerprint,
        )
        digest = Sha256DigestProvider()
        service = QuantitativeFindingGenerationService(
            generator=DeterministicQuantitativeFindingProposalGenerator(),
            support_validator=CanonicalQuantFindingSupportValidator(
                digest_provider=digest, dataset=dataset, run_id=dataset.run_id,
            ), digest_provider=digest,
        )
        finding = service.generate(statistical_results=(source,)).accepted_findings[0]
        authority = finding.canonical_authority
        self.assertEqual(authority.run_id, dataset.run_id)
        self.assertEqual(authority.dataset_version_id, dataset.version_id)
        self.assertEqual(authority.dataset_fingerprint, dataset.dataset_fingerprint)
        self.assertEqual(authority.source_n, dataset.row_count)
        self.assertEqual(authority.result_refs[0].result_id, source.result_id)
        self.assertEqual(authority.denominators, (source.denominator,))
        stale = service.generate(statistical_results=(replace(source, dataset_fingerprint="stale"),))
        self.assertEqual(stale.accepted_findings, ())
        self.assertIn("outside pinned dataset", stale.rejected_findings[0].reason)

    def test_new_run_pin_is_exact_and_legacy_absence_stays_legacy(self):
        self.assertFalse(resolve_post_analysis_pin(None, method_pin={"legacy": True}))
        self.assertTrue(resolve_post_analysis_pin(POST_ANALYSIS_VERSION, method_pin={"bound": True}))
        with self.assertRaises(ValueError):
            resolve_post_analysis_pin("unrecognized", method_pin={"bound": True})

    def test_canonical_significant_and_non_significant_comparisons(self):
        for method, statistic in (("INDEPENDENT_TWO_PROPORTION_Z_TEST", "VALID_PERCENTAGE"),
                                  ("INDEPENDENT_WELCH_T_TEST", "NUMERIC_MEAN")):
            for significant in (True, False):
                with self.subTest(method=method, significant=significant):
                    first = result("group-a", "55", statistic_type=statistic)
                    second = result("group-b", "44", statistic_type=statistic)
                    compared = replace(comparison(first, second, significant=significant),
                                       method=method)
                    generated = self.service.generate(
                        statistical_results=(first, second),
                        comparison_results=(compared,),
                    )
                    self.assertFalse(generated.rejected_findings)
                    bound = next(item for item in generated.accepted_findings
                                 if item.comparison_result_refs)
                    self.assertEqual(bound.comparison_result_refs[0].comparison_result_id,
                                     compared.comparison_result_id)
                    self.assertEqual(bound.claim.value, compared.observed_difference)
                    self.assertEqual(bound.claim.claim_type.value,
                                     "SIGNIFICANT_COMPARISON" if significant else
                                     "NON_SIGNIFICANT_COMPARISON")

    def test_cross_tab_weighting_and_missingness_stay_bound_to_exact_results(self):
        cross = result("cross-tab", "36.25", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE",
                       column="group-a")
        weighted = result("weighted-share", "41.75", statistic_type="WEIGHTED_PERCENTAGE",
                          weighting="WEIGHTED", weight_fingerprint="weights-v1")
        generated = self.service.generate(statistical_results=(cross, weighted))
        self.assertEqual(generated.rejected_findings, ())
        by_result = {item.statistical_result_refs[0].result_id: item
                     for item in generated.accepted_findings}
        self.assertEqual(set(by_result), {cross.result_id, weighted.result_id})
        for source in (cross, weighted):
            finding = by_result[source.result_id]
            self.assertEqual(finding.claim.value, source.value)
            self.assertEqual(finding.statistical_result_refs[0].reproducibility_fingerprint,
                             source.reproducibility_fingerprint)
            self.assertEqual(finding.claim.weighting_status, source.weighting_status)
            self.assertEqual(finding.claim.weight_set_fingerprint, source.weight_set_fingerprint)
        self.assertEqual(by_result[cross.result_id].claim.display_value, "36.3")
        self.assertEqual(by_result[weighted.result_id].claim.display_value, "41.8")


class QNT03PinnedCreationTests(ApiTestCase):
    def test_new_cmf_run_pins_version_before_dataset_and_checkpoint_cannot_change_it(self):
        from application.methods.quantitative.pin import (
            METHOD_PIN, POST_ANALYSIS_PIN, REVIEW_PIN, REVIEW_VERSION,
        )

        self.container.quantitative_ui_service.cmf_quant_enabled = True
        response = self.client.post("/ui/quantitative/studies", data={
            "title": "Synthetic QNT-03 pin", "description": "offline",
            "submission_key": "qnt03-pin-fixture",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        run_id = response.headers["location"].rsplit("/", 1)[-1]
        results = self.container.workflow_service.get_task_results(run_id)
        self.assertEqual(results[POST_ANALYSIS_PIN], POST_ANALYSIS_VERSION)
        self.assertEqual(results[REVIEW_PIN], REVIEW_VERSION)
        self.assertIn(METHOD_PIN, results)
        replay = checkpoint_results(results, {POST_ANALYSIS_PIN: "mutated"})
        self.assertEqual(replay[POST_ANALYSIS_PIN], POST_ANALYSIS_VERSION)
        self.assertEqual(checkpoint_results(results, {REVIEW_PIN: "mutated"})[REVIEW_PIN],
                         REVIEW_VERSION)


if __name__ == "__main__":
    unittest.main()
