from __future__ import annotations

import unittest
from dataclasses import replace

from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.insight_support_canonicalization import (
    semantic_evidence_context_projection,
)
from domain.quantitative.finding import QuantitativeSemanticEvidenceContext
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import result
from tests.application.quantitative.test_property_qi_llm_assisted_finding_generation import (
    FakeProposalGenerator,
)


def context_for(authority, *, population):
    digest = Sha256DigestProvider()
    provenance = (
        ("STATISTICAL_RESULT", authority.result_id, authority.reproducibility_fingerprint),
        ("VARIABLE_DEFINITION", authority.variable_id, authority.variable_fingerprint),
        ("CODEBOOK_VERSION", "codebook-v1", authority.codebook_fingerprint),
        ("RC_ANALYSIS_PLAN", "plan-v1", "plan-fingerprint"),
        ("RD_EXECUTION_MANIFEST", "rd-v1", "rd-fingerprint"),
    )
    values = {
        "result": (authority.result_id, authority.reproducibility_fingerprint),
        "variable": (authority.variable_id, authority.variable_fingerprint),
        "variable_label": "tool capability statement",
        "question_context": "Q43 attitudinal battery",
        "category_code": canonical_scalar(authority.category_value),
        "category_label": "top-two-box agreement",
        "filter": authority.filter_definition,
        "base": authority.base_definition,
        "denominator": canonical_scalar(authority.denominator),
        "population_description": population,
        "value": canonical_scalar(authority.value),
        "display_value": "77.8",
        "weighting": (authority.weighting_status, authority.weight_set_fingerprint),
        "provenance": provenance,
        "version": "P1_18_SEMANTIC_EVIDENCE_V1",
    }
    fingerprint = canonical_digest(values, digest_provider=digest)
    return QuantitativeSemanticEvidenceContext(
        f"qi-context-{fingerprint}", authority.result_id,
        authority.reproducibility_fingerprint, authority.variable_id,
        authority.variable_fingerprint, "tool capability statement",
        "Q43 attitudinal battery", authority.category_value,
        "top-two-box agreement", authority.filter_definition,
        authority.base_definition, authority.denominator, population,
        authority.value, "77.8", authority.weighting_status,
        authority.weight_set_fingerprint, provenance, fingerprint,
    )


def run(prose, *, population="qualified power-tool users completing Q43 valid responses"):
    authority = replace(
        result("p1-21-result", "77.8473"),
        category_value=5,
        denominator=799,
        filter_definition="Q43_SUBSTANTIVE",
        base_definition="VALID_RESPONSES",
        weighting_status="UNWEIGHTED",
    )
    context = context_for(authority, population=population)
    generator = FakeProposalGenerator({"proposals": [{
        "claim_type": "DESCRIPTIVE_VALUE",
        "finding_text": prose,
        "selected_result_ids": [authority.result_id],
        "selected_comparison_ids": [],
    }]})
    digest = Sha256DigestProvider()
    generated = QuantitativeFindingGenerationService(
        generator=generator,
        support_validator=QuantitativeFindingSupportValidator(digest_provider=digest),
        digest_provider=digest,
    ).generate(
        statistical_results=(authority,),
        semantic_evidence_contexts={authority.result_id: context},
    )
    return generated, context


class P121CanonicalPopulationContextTests(unittest.TestCase):
    def test_provider_retained_population_is_accepted(self):
        generated, context = run(
            "Among qualified power-tool users completing Q43 valid responses, 77.8% indicated agreement."
        )
        self.assertEqual(generated.acceptance_summary["accepted"], 1)
        self.assertIn(context.population_description, generated.accepted_findings[0].text)

    def test_provider_population_omission_is_deterministically_attached(self):
        generated, context = run("77.8% indicated that tools increase their ability to solve tasks.")
        self.assertEqual(generated.acceptance_summary["accepted"], 1)
        finding = generated.accepted_findings[0]
        self.assertEqual(finding.semantic_evidence_context, context)
        self.assertIn(f"population={context.population_description}", finding.text)

    def test_provider_population_broadening_is_rejected(self):
        generated, _ = run("77.8% of all respondents indicated agreement.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_provider_population_identity_change_is_rejected(self):
        generated, _ = run("77.8% of retail customers indicated agreement.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_provider_denominator_change_is_rejected(self):
        generated, _ = run("Among 811 respondents, 77.8% indicated agreement.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_provider_weighting_change_is_rejected(self):
        generated, _ = run("The weighted result was 77.8%.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_unsupported_causal_claim_is_rejected(self):
        generated, _ = run("The 77.8% result proves tools cause improved task outcomes.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_unsupported_significance_claim_is_rejected(self):
        generated, _ = run("The 77.8% result is statistically significant.")
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_study_1_population_generalization_remains_rejected(self):
        generated, _ = run(
            "Among interior-paint users, the response was 77.8%.",
            population=None,
        )
        self.assertEqual(generated.acceptance_summary["accepted"], 0)

    def test_study_3_omission_accepts_but_all_consumers_rejects(self):
        omitted, _ = run("77.8% indicated that tools increase their ability to solve tasks.")
        broadened, _ = run("77.8% of all Ukrainian consumers indicated agreement.")
        self.assertEqual(omitted.acceptance_summary["accepted"], 1)
        self.assertEqual(broadened.acceptance_summary["accepted"], 0)

    def test_study_2_retained_service_population_remains_valid(self):
        population = "customers completing the service interaction survey"
        generated, _ = run(
            f"Among {population}, 77.8% indicated agreement.",
            population=population,
        )
        self.assertEqual(generated.acceptance_summary["accepted"], 1)

    def test_downstream_projection_retains_population_context(self):
        generated, context = run("77.8% indicated agreement.")
        projection = semantic_evidence_context_projection(
            generated.accepted_findings[0].semantic_evidence_context
        )
        self.assertEqual(projection["population_description"], context.population_description)


if __name__ == "__main__":
    unittest.main()
