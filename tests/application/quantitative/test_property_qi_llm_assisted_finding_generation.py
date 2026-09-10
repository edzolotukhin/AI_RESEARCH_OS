from __future__ import annotations

import inspect
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

from application.quantitative.finding_generation import (
    PROMPT_VERSION,
    QuantitativeFindingGenerationService,
)
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from domain.quantitative.finding import (
    QuantitativeSemanticEvidenceContext,
    QuantitativeSupportStatus,
)
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

    def test_p1_18_benchmark_semantic_context_is_bound_and_fail_closed(self):
        digest = Sha256DigestProvider()
        authority = replace(
            result("e09e22b4-e870-5e11-9897-037b4cf11a34", "22.020202"),
            variable_id="var-11-Q12",
            variable_fingerprint="variable-fingerprint",
            category_value=5,
            denominator=1485,
            filter_definition="ALL_ROWS",
            base_definition="VALID_RESPONSES",
            weighting_status="UNWEIGHTED",
        )
        provenance = (
            ("STATISTICAL_RESULT", authority.result_id, authority.reproducibility_fingerprint),
            ("VARIABLE_DEFINITION", authority.variable_id, authority.variable_fingerprint),
            ("CODEBOOK_VERSION", "codebook-v1", authority.codebook_fingerprint),
            ("RC_ANALYSIS_PLAN", "plan-v1", "plan-fingerprint"),
            ("RD_EXECUTION_MANIFEST", "rd-v1", "rd-fingerprint"),
        )
        payload = {
            "result": (authority.result_id, authority.reproducibility_fingerprint),
            "variable": (authority.variable_id, authority.variable_fingerprint),
            "variable_label": "household wall-painting repair frequency",
            "question_context": "household wall-painting repair frequency",
            "category_code": canonical_scalar(5),
            "category_label": "once every five years",
            "filter": "ALL_ROWS",
            "base": "VALID_RESPONSES",
            "denominator": canonical_scalar(1485),
            "population_description": None,
            "value": canonical_scalar(authority.value),
            "display_value": "22.0",
            "weighting": ("UNWEIGHTED", None),
            "provenance": provenance,
            "version": "P1_18_SEMANTIC_EVIDENCE_V1",
        }
        fingerprint = canonical_digest(payload, digest_provider=digest)
        context = QuantitativeSemanticEvidenceContext(
            f"qi-context-{fingerprint}", authority.result_id,
            authority.reproducibility_fingerprint, authority.variable_id,
            authority.variable_fingerprint,
            "household wall-painting repair frequency",
            "household wall-painting repair frequency", 5,
            "once every five years", "ALL_ROWS", "VALID_RESPONSES", 1485,
            None, authority.value, "22.0", "UNWEIGHTED", None,
            provenance, fingerprint,
        )
        response = {"proposals": [{
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": (
                "For household wall-painting repair frequency, once every five years "
                "was 22.0% (N=1,485; ALL_ROWS; VALID_RESPONSES; UNWEIGHTED)."
            ),
            "selected_result_ids": [authority.result_id],
            "selected_comparison_ids": [],
        }]}
        service, generator = self.service(response)
        generated = service.generate(
            statistical_results=(authority,),
            semantic_evidence_contexts={authority.result_id: context},
        )
        finding = generated.accepted_findings[0]
        self.assertEqual(finding.semantic_evidence_context, context)
        self.assertIn("once every five years", generator.prompts[0])
        self.assertNotIn("interior-paint users", generator.prompts[0])
        self.assertEqual(finding.statistical_result_refs[0].result_id, authority.result_id)
        with self.assertRaisesRegex(
            Exception, "omits required canonical semantic evidence context"
        ):
            service._validator.validate(
                replace(finding, semantic_evidence_context=None),
                statistical_results={authority.result_id: authority},
                semantic_evidence_contexts={authority.result_id: context},
            )

        for changed in (
            {"category_label": "another label"},
            {"question_context": "another question"},
            {"denominator": 1484},
            {"filter_definition": "FILTERED"},
            {"base_definition": "ALL_RESPONSES"},
            {"population_description": "interior-paint users"},
            {"value": Decimal("21")},
            {"weighting_status": "WEIGHTED"},
            {"fingerprint": "wrong"},
            {"provenance": provenance[:-1]},
        ):
            corrupted = replace(context, **changed)
            with self.assertRaisesRegex(Exception, "semantic evidence context"):
                service._validator.validate(
                    finding,
                    statistical_results={authority.result_id: authority},
                    semantic_evidence_contexts={authority.result_id: corrupted},
                )

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

    def test_bundle_bound_selection_preserves_non_terminating_decimal_exactly(self):
        authority = result("percentage", "22.02020202020202020202020202", category=5)
        response = {"proposals": [{
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": "Category 5 represents 22.0% of valid responses.",
            "selected_result_ids": [authority.result_id],
            "selected_comparison_ids": [],
            "limitation_note": None,
        }]}
        service, generator = self.service(response)

        generated = service.generate(statistical_results=(authority,))

        self.assertEqual(generated.acceptance_summary["accepted"], 1)
        finding = generated.accepted_findings[0]
        self.assertEqual(
            finding.claim.value, Decimal("22.02020202020202020202020202")
        )
        self.assertEqual(finding.claim.display_value, "22.0")
        prompt = generator.prompts[0]
        self.assertIn('"selected_result_ids"', prompt)
        self.assertIn('"allowed_claim_types"', prompt)
        self.assertNotIn('"value":"exact decimal or null"', prompt)
        provider_bundle = prompt.split("AUTHORITATIVE_BUNDLE=", 1)[1]
        self.assertNotIn('"reproducibility_fingerprint"', provider_bundle)
        self.assertNotIn('"value":{"type":"decimal"', provider_bundle)

    def test_frozen_style_percentage_selections_accept_but_count_is_not_selectable(self):
        values = (
            ("p5", "22.02020202020202020202020202", 5, "22.0"),
            ("p11", "15.15151515151515151515151515", 11, "15.2"),
            ("p10", "17.50841750841750841750841751", 10, "17.5"),
            ("p3", "9.090909090909090909090909091", 3, "9.1"),
        )
        authorities = tuple(
            result(identity, value, category=category)
            for identity, value, category, _ in values
        )
        count = result("count", "101", statistic_type="CATEGORY_COUNT", category=2)
        response = {"proposals": [
            {
                "claim_type": "DESCRIPTIVE_VALUE",
                "finding_text": f"Category {category} represents {display}% of valid responses.",
                "selected_result_ids": [identity],
                "selected_comparison_ids": [],
            }
            for identity, _, category, display in values
        ]}
        service, generator = self.service(response)

        generated = service.generate(statistical_results=authorities + (count,))

        self.assertEqual(generated.acceptance_summary["accepted"], 4)
        self.assertEqual(
            tuple(item.claim.value for item in generated.accepted_findings),
            tuple(item.value for item in authorities),
        )
        self.assertNotIn('"result_id":"count"', generator.prompts[0])
        count_only, count_generator = self.service({"proposals": []})
        no_support = count_only.generate(statistical_results=(count,))
        self.assertEqual(no_support.acceptance_summary["accepted"], 0)
        self.assertEqual(no_support.generation_metadata["generation_passes"], 0)
        self.assertEqual(count_generator.prompts, [])

    def test_selector_contract_rejects_nearby_prose_and_model_authority_fields(self):
        authority = result("percentage", "22.02020202020202020202020202", category=5)
        base = {
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": "Category 5 represents 22.0% of valid responses.",
            "selected_result_ids": [authority.result_id],
            "selected_comparison_ids": [],
        }
        cases = (
            dict(base, finding_text="Category 5 represents 21.9% of valid responses."),
            dict(base, value=22.02020202020202),
            dict(base, statistic_type="CATEGORY_COUNT"),
            dict(base, base_definition="ALL_RESPONSES"),
        )
        service, _ = self.service({"proposals": list(cases)})

        generated = service.generate(statistical_results=(authority,))

        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertEqual(generated.acceptance_summary["rejected"], 4)
        self.assertTrue(any("canonical display" in item.reason for item in generated.rejected_findings))
        self.assertTrue(any("contradicts canonical support" in item.reason for item in generated.rejected_findings))

    def test_wrong_selector_claim_pair_and_replay_fail_closed_or_identical(self):
        authority = result("percentage", "22.02020202020202020202020202", category=5)
        valid = {"proposals": [{
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": "Category 5 represents 22.0% of valid responses.",
            "selected_result_ids": [authority.result_id],
            "selected_comparison_ids": [],
        }]}
        first, _ = self.service(valid)
        second, _ = self.service(valid)
        self.assertEqual(
            first.generate(statistical_results=(authority,)),
            second.generate(statistical_results=(authority,)),
        )
        selector_finding = first.generate(
            statistical_results=(authority,)
        ).accepted_findings[0]
        legacy = proposal(authority, "DESCRIPTIVE_VALUE")
        legacy["finding_text"] = valid["proposals"][0]["finding_text"]
        legacy["limitation_note"] = None
        legacy_service, _ = self.service({"proposals": [legacy]})
        self.assertEqual(
            selector_finding.finding_id,
            legacy_service.generate(
                statistical_results=(authority,)
            ).accepted_findings[0].finding_id,
        )

        invalid = {"proposals": [
            dict(valid["proposals"][0], selected_result_ids=["unknown"]),
            dict(valid["proposals"][0], claim_type="NUMERIC_SUMMARY"),
        ]}
        service, _ = self.service(invalid)
        generated = service.generate(statistical_results=(authority,))
        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertEqual(generated.acceptance_summary["rejected"], 2)


    def test_dominant_eligible_percentage_is_application_ranked_and_qh_accepted(self):
        low = result("low", "12", category="A")
        dominant = result("dominant", "22.02020202020202020202020202", category="B")
        middle = result("middle", "18", category="C")
        response = {"proposals": [{
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": "Category B represents 22.0% of valid responses.",
            "selected_result_ids": [dominant.result_id],
            "selected_comparison_ids": [],
        }]}
        service, generator = self.service(response)

        generated = service.generate(statistical_results=(low, dominant, middle))

        self.assertEqual(generated.acceptance_summary, {"proposed": 1, "parsed": 1, "accepted": 1, "rejected": 0})
        finding = generated.accepted_findings[0]
        self.assertEqual(finding.claim.value, dominant.value)
        self.assertEqual(finding.statistical_result_refs[0].reproducibility_fingerprint, dominant.reproducibility_fingerprint)
        bundle = json.loads(generator.prompts[0].split("AUTHORITATIVE_BUNDLE=", 1)[1])
        cues = {item["result_id"]: item["selection_materiality"] for item in bundle["statistical_results"]}
        self.assertEqual(cues["dominant"]["rank_within_distribution"], 1)
        self.assertTrue(cues["dominant"]["is_dominant"])
        self.assertEqual(cues["low"]["rank_within_distribution"], 3)
        self.assertFalse(cues["low"]["is_dominant"])

    def test_empty_selection_fails_only_when_application_identifies_dominant_result(self):
        low = result("low", "12", category="A")
        dominant = result("dominant", "22", category="B")
        service, generator = self.service({"proposals": []})

        with self.assertRaisesRegex(ValueError, "abstained despite application-ranked dominant"):
            service.generate(statistical_results=(low, dominant))
        self.assertEqual(len(generator.prompts), 1)

        numeric = result("mean", "7.4", statistic_type="NUMERIC_MEAN", category=None)
        service, generator = self.service({"proposals": []})
        generated = service.generate(statistical_results=(numeric,))
        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertEqual(generated.generation_metadata["generation_passes"], 1)
        self.assertEqual(len(generator.prompts), 1)

    def test_no_presentation_eligible_support_abstains_without_provider_dispatch(self):
        ineligible = replace(result("hidden", "42"), presentation_eligible=False)
        service, generator = self.service({"proposals": []})

        generated = service.generate(statistical_results=(ineligible,))

        self.assertEqual(generated.acceptance_summary, {"proposed": 0, "parsed": 0, "accepted": 0, "rejected": 0})
        self.assertEqual(generated.generation_metadata["generation_passes"], 0)
        self.assertEqual(generated.generation_metadata["abstention_reason"], "NO_PRESENTATION_ELIGIBLE_QH_SUPPORT")
        self.assertEqual(generator.prompts, [])

    def test_ineligible_or_model_authored_materiality_cannot_enter_qh_support(self):
        ineligible = replace(result("hidden", "42"), presentation_eligible=False)
        numeric = result("mean", "7.4", statistic_type="NUMERIC_MEAN", category=None)
        response = {"proposals": [
            {
                "claim_type": "DESCRIPTIVE_VALUE",
                "finding_text": "Category X represents 42.0% of valid responses.",
                "selected_result_ids": [ineligible.result_id],
                "selected_comparison_ids": [],
            },
            {
                "claim_type": "NUMERIC_SUMMARY",
                "finding_text": "The mean is 7.4.",
                "selected_result_ids": [numeric.result_id],
                "selected_comparison_ids": [],
                "selection_materiality": {"is_dominant": True},
            },
        ]}
        service, _ = self.service(response)

        generated = service.generate(statistical_results=(ineligible, numeric))

        self.assertEqual(generated.acceptance_summary["accepted"], 0)
        self.assertEqual(generated.acceptance_summary["rejected"], 2)
        self.assertTrue(any("outside the authoritative bundle" in item.reason for item in generated.rejected_findings))
        self.assertTrue(any("must not supply design lineage" in item.reason for item in generated.rejected_findings))

    def test_materiality_projection_recomputes_from_exact_result_authority(self):
        low = result("low", "12", category="A")
        high = result("high", "22", category="B")
        service, _ = self.service({"proposals": []})
        cues = service._selection_materiality((low, high))
        self.assertTrue(cues["high"]["is_dominant"])
        self.assertFalse(cues["low"]["is_dominant"])
        with self.assertRaisesRegex(ValueError, "materiality metadata is inconsistent"):
            service._bundle(
                (low, high), (), {}, (),
                materiality={"low": cues["low"], "high": {**cues["high"], "is_dominant": False}},
            )
if __name__ == "__main__":
    unittest.main()
