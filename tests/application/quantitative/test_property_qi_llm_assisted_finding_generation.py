from __future__ import annotations

import inspect
import unittest
from copy import deepcopy

from application.quantitative.finding_generation import (
    PROMPT_VERSION,
    QuantitativeFindingGenerationService,
)
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from domain.quantitative.finding import QuantitativeSupportStatus
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import (
    comparison,
    result,
)


class FakeProposalGenerator:
    def __init__(self, response, identity="offline-fake-v1"):
        self.response = response
        self._identity = identity
        self.prompts = []

    @property
    def identity(self):
        return self._identity

    def generate(self, prompt):
        self.prompts.append(prompt)
        return deepcopy(self.response)


def proposal(authority, claim_type, *, value=None, category=None, refs=None, comparisons=None, direction=None, display=None, **changes):
    payload = {
        "claim_type": claim_type,
        "finding_text": f"Aggregate finding based on {authority.result_id}.",
        "statistical_result_refs": refs or [authority.result_id],
        "comparison_result_refs": comparisons or [],
        "value": str(authority.value if value is None else value),
        "display_value": display if display is not None else f"{authority.value:.1f}",
        "rounding_decimal_places": 1,
        "variable_id": authority.variable_id,
        "statistic_type": authority.statistic_type,
        "category_value": authority.category_value if category is None else category,
        "filter_definition": authority.filter_definition,
        "base_definition": authority.base_definition,
        "weighting_status": authority.weighting_status,
        "weight_set_fingerprint": authority.weight_set_fingerprint,
        "direction": direction,
        "limitation_note": "Aggregate base is inspectable.",
    }
    payload.update(changes)
    return payload


class PropertyQILLMAssistedFindingGenerationTests(unittest.TestCase):
    def service(self, response):
        generator = FakeProposalGenerator(response)
        digest = Sha256DigestProvider()
        return QuantitativeFindingGenerationService(
            generator=generator,
            support_validator=QuantitativeFindingSupportValidator(digest_provider=digest),
            digest_provider=digest,
        ), generator

    def test_all_five_supported_claim_types_are_accepted(self):
        percentage = result("percentage", "42")
        mean = result("mean", "7.4", statistic_type="NUMERIC_MEAN", category=None)
        nps = result("nps", "36", statistic_type="NPS", category=None)
        a = result("a", "70", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="WOMEN")
        b = result("b", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="MEN")
        qg = comparison(a, b)
        proposals = [
            proposal(percentage, "DESCRIPTIVE_VALUE"),
            proposal(mean, "NUMERIC_SUMMARY"),
            proposal(nps, "KPI_VALUE"),
            proposal(a, "DESCRIPTIVE_COMPARISON", refs=[a.result_id, b.result_id], value="30", direction="HIGHER", category="X", display=None),
            proposal(a, "SIGNIFICANT_COMPARISON", refs=[a.result_id, b.result_id], comparisons=[qg.comparison_result_id], value="30", direction="HIGHER", category="X", display=None),
        ]
        service, generator = self.service({"proposals": proposals})
        generated = service.generate(statistical_results=(percentage, mean, nps, a, b), comparison_results=(qg,))
        self.assertEqual(len(generator.prompts), 1)
        self.assertEqual(generated.acceptance_summary, {"proposed": 5, "parsed": 5, "accepted": 5, "rejected": 0})
        self.assertTrue(all(item.support_validation_status is QuantitativeSupportStatus.SUPPORTED for item in generated.accepted_findings))
        self.assertEqual(generated.prompt_version, PROMPT_VERSION)

    def test_invented_number_and_unknown_reference_are_rejected_while_model_fingerprint_is_ignored(self):
        authority = result("percentage", "42")
        canonical = result("canonical", "42")
        proposals = [
            proposal(authority, "DESCRIPTIVE_VALUE", value="43", display="43.0"),
            proposal(authority, "DESCRIPTIVE_VALUE", refs=["unknown"]),
            proposal(
                canonical,
                "DESCRIPTIVE_VALUE",
                statistical_result_fingerprints={"canonical": "model-supplied-fingerprint"},
            ),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(statistical_results=(authority, canonical))
        self.assertEqual(generated.acceptance_summary["accepted"], 1)
        self.assertEqual(generated.acceptance_summary["rejected"], 2)
        self.assertEqual(
            generated.accepted_findings[0].statistical_result_refs[0].reproducibility_fingerprint,
            canonical.reproducibility_fingerprint,
        )
        self.assertTrue(all(item.reason for item in generated.rejected_findings))

    def test_significance_without_qg_and_non_significant_qg_are_rejected(self):
        a = result("a", "55", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A")
        b = result("b", "50", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B")
        nonsig = comparison(a, b, significant=False)
        proposals = [
            proposal(a, "SIGNIFICANT_COMPARISON", refs=["a", "b"], value="5", direction="HIGHER", category="X"),
            proposal(a, "SIGNIFICANT_COMPARISON", refs=["a", "b"], comparisons=[nonsig.comparison_result_id], value="5", direction="HIGHER", category="X"),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(statistical_results=(a, b), comparison_results=(nonsig,))
        self.assertEqual(len(generated.rejected_findings), 2)
        self.assertTrue(any("ComparisonResult" in item.reason for item in generated.rejected_findings))
        self.assertTrue(any("significance wording" in item.reason for item in generated.rejected_findings))

    def test_weight_filter_rounding_and_direction_adversaries_are_rejected(self):
        authority = result("percentage", "42")
        a = result("a", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A")
        b = result("b", "60", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B")
        proposals = [
            proposal(authority, "DESCRIPTIVE_VALUE", weighting_status="WEIGHTED", weight_set_fingerprint="wrong"),
            proposal(authority, "DESCRIPTIVE_VALUE", filter_definition="region=NORTH"),
            proposal(authority, "DESCRIPTIVE_VALUE", base_definition="WRONG_BASE"),
            proposal(authority, "DESCRIPTIVE_VALUE", display="41.9"),
            proposal(a, "DESCRIPTIVE_COMPARISON", refs=["a", "b"], value="-20", direction="HIGHER", category="X"),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(statistical_results=(authority, a, b))
        self.assertEqual(len(generated.rejected_findings), 5)
        self.assertEqual(len(generated.accepted_findings), 0)

    def test_prompt_is_bounded_aggregate_only_and_contains_required_authority_rules(self):
        authority = result("percentage", "42")
        service, generator = self.service({"proposals": [proposal(authority, "DESCRIPTIVE_VALUE")]})
        generated = service.generate(
            statistical_results=(authority,),
            display_labels={authority.result_id: "Brand selection percentage"},
            limitations=("Small aggregate base; interpret cautiously.",),
        )
        prompt = generator.prompts[0]
        for required in ("only the supplied result ids", "do not calculate new values", "do not infer significance", "weighted/unweighted", "result_id", "unweighted_n"):
            self.assertIn(required, prompt.lower())
        for forbidden in ("respondent rows", "Alice Example", "+64 21 555 0199", "alice@example.test", "raw DatasetVersion contents"):
            self.assertNotIn(forbidden, prompt)
        self.assertEqual(generated.generation_metadata, {"generation_passes": 1, "repair_attempts": 0})

    def test_direct_pii_in_inputs_or_generated_text_never_becomes_accepted(self):
        authority = result("percentage", "42")
        service, generator = self.service({"proposals": [proposal(authority, "DESCRIPTIVE_VALUE", finding_text="Call +64 21 555 0199 about 42%.")]})
        generated = service.generate(statistical_results=(authority,))
        self.assertEqual(len(generated.accepted_findings), 0)
        self.assertEqual(len(generated.rejected_findings), 1)
        self.assertEqual(len(generator.prompts), 1)
        service, generator = self.service({"proposals": []})
        with self.assertRaisesRegex(ValueError, "PII"):
            service.generate(statistical_results=(authority,), display_labels={authority.result_id: "alice@example.test"})
        self.assertEqual(generator.prompts, [])

    def test_same_fake_output_is_deterministic_and_rejections_remain_auditable(self):
        authority = result("percentage", "42")
        response = {"proposals": [proposal(authority, "DESCRIPTIVE_VALUE"), proposal(authority, "DESCRIPTIVE_VALUE", value="99", display="99.0")]}
        first_service, first_generator = self.service(response)
        second_service, second_generator = self.service(response)
        first = first_service.generate(statistical_results=(authority,))
        second = second_service.generate(statistical_results=(authority,))
        self.assertEqual(first, second)
        self.assertEqual(first_generator.prompts, second_generator.prompts)
        self.assertEqual(len(first.rejected_findings), 1)
        rejection = first.rejected_findings[0]
        self.assertEqual(rejection.proposal_ordinal, 2)
        self.assertIn("99", str(rejection.proposal_payload))
        self.assertTrue(rejection.rejection_fingerprint)

    def test_qh_and_desk_boundaries_remain_separate_without_external_clients(self):
        import application.quantitative.finding_generation as module
        source = inspect.getsource(module)
        for forbidden in ("domain.findings", "domain.evidence", "InformationNeed", "openai", "tavily", "respondent_rows", "get_parsed_rows"):
            self.assertNotIn(forbidden, source)
        self.assertIn("QuantitativeFindingSupportValidator", source)


if __name__ == "__main__":
    unittest.main()
