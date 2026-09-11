from __future__ import annotations

import inspect
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.insight_support_canonicalization import (
    canonical_finding_support_bundle,
)
from application.quantitative.insight_synthesis import (
    PROMPT_VERSION,
    VALIDATION_VERSION,
    QuantitativeInsightSynthesisService,
    QuantitativeInsightValidator,
)
from domain.findings.insight import Insight as DeskInsight
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeSemanticEvidenceContext, QuantitativeSupportStatus
from domain.quantitative.insight import QuantitativeInsightValidationStatus
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import (
    comparison,
    finding,
    result,
)


class FakeInsightGenerator:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    @property
    def identity(self):
        return "offline-insight-fake-v1"

    def generate(self, prompt):
        self.prompts.append(prompt)
        return deepcopy(self.response)


def insight_proposal(kind, text, supports, *, values=(), direction=None, limitation=None, fingerprints=None):
    return {
        "insight_type": kind,
        "insight_text": text,
        "supporting_finding_ids": [item.finding_id for item in supports],
        "referenced_display_values": list(values),
        "direction": direction,
        "limitation_note": limitation,
    }


class PropertyQJQuantitativeInsightSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()
        self.qh = QuantitativeFindingSupportValidator(digest_provider=self.digest)

    def supported_single(self, authority, claim_type, *, finding_id, display=None):
        raw = finding(
            claim_type,
            (authority,),
            value=str(authority.value),
            statistic_type=authority.statistic_type,
            category=authority.category_value,
            display_value=display if display is not None else f"{authority.value:.1f}",
        )
        raw = replace(raw, finding_id=finding_id)
        return self.qh.validate(raw, statistical_results={authority.result_id: authority})

    def supported_comparison(self, a, b, *, finding_id, significant=False):
        qg = comparison(a, b) if significant else None
        raw = finding(
            QuantitativeClaimType.SIGNIFICANT_COMPARISON if significant else QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
            (a, b),
            value=str(a.value - b.value),
            statistic_type=a.statistic_type,
            category=a.category_value,
            direction="HIGHER" if a.value > b.value else "LOWER",
            comparison=qg,
        )
        raw = replace(raw, finding_id=finding_id)
        validated = self.qh.validate(
            raw,
            statistical_results={a.result_id: a, b.result_id: b},
            comparison_results={qg.comparison_result_id: qg} if qg else {},
        )
        return validated

    def service(self, response):
        generator = FakeInsightGenerator(response)
        return QuantitativeInsightSynthesisService(
            generator=generator,
            validator=QuantitativeInsightValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        ), generator

    def r6_semantic_finding(self):
        authority = replace(
            result("r6-03", "22.020202020202", category=5),
            denominator=1485,
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
            "variable_label": "household wall-painting renovation frequency",
            "question_context": "household wall-painting renovation frequency",
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
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        context = QuantitativeSemanticEvidenceContext(
            f"qi-context-{fingerprint}", authority.result_id,
            authority.reproducibility_fingerprint, authority.variable_id,
            authority.variable_fingerprint,
            "household wall-painting renovation frequency",
            "household wall-painting renovation frequency", 5,
            "once every five years", "ALL_ROWS", "VALID_RESPONSES", 1485,
            None, Decimal("22.020202020202"), "22.0", "UNWEIGHTED", None,
            provenance, fingerprint,
        )
        raw = replace(
            finding(
                QuantitativeClaimType.DESCRIPTIVE_VALUE, (authority,),
                value=str(authority.value), statistic_type=authority.statistic_type,
                category=5, display_value="22.0",
            ),
            finding_id="r6-03-finding",
            text=(
                "For household wall-painting renovation frequency, once every "
                "five years was 22.0% (N=1,485; ALL_ROWS; "
                "VALID_RESPONSES; UNWEIGHTED)."
            ),
            semantic_evidence_context=context,
        )
        accepted = self.qh.validate(
            raw,
            statistical_results={authority.result_id: authority},
            semantic_evidence_contexts={authority.result_id: context},
        )
        return authority, accepted

    def test_r6_semantics_reach_qj_and_legitimate_abstention_is_preserved(self):
        _, accepted = self.r6_semantic_finding()
        service, generator = self.service({"proposals": []})
        generated = service.generate(findings=(accepted,))
        bundle = json.loads(generator.prompts[0].split("ACCEPTED_FINDINGS=", 1)[1])
        semantic = bundle[0]["semantic_evidence_context"]

        self.assertEqual(generated.accepted_insights, ())
        self.assertEqual(generated.acceptance_summary["proposed"], 0)
        self.assertEqual(semantic["question_context"], "household wall-painting renovation frequency")
        self.assertEqual(semantic["category_label"], "once every five years")
        self.assertEqual(semantic["exact_value"], {"type": "decimal", "value": "22.020202020202"})
        self.assertEqual(semantic["display_value"], "22.0")
        self.assertEqual(semantic["denominator"], {"type": "integer", "value": "1485"})
        self.assertEqual(semantic["filter_definition"], "ALL_ROWS")
        self.assertEqual(semantic["base_definition"], "VALID_RESPONSES")
        self.assertEqual(semantic["weighting_status"], "UNWEIGHTED")
        self.assertNotIn("population_description", semantic)
        self.assertIn("return an empty proposals array", generator.prompts[0])

    def test_semantic_authority_changes_bind_qj_fingerprint_deterministically(self):
        _, accepted = self.r6_semantic_finding()
        first = canonical_finding_support_bundle((accepted,))
        second = canonical_finding_support_bundle((accepted,))
        self.assertEqual(first, second)
        baseline = canonical_digest(first, digest_provider=self.digest)

        context = accepted.semantic_evidence_context
        changes = (
            {"category_label": "once every four years"},
            {"question_context": "different question"},
            {"denominator": 1484},
            {"value": Decimal("21")},
            {"population_description": "authorized households"},
            {"result_fingerprint": "different-result"},
            {"variable_fingerprint": "different-variable"},
        )
        for change in changes:
            changed = replace(accepted, semantic_evidence_context=replace(context, **change))
            self.assertNotEqual(
                baseline,
                canonical_digest(
                    canonical_finding_support_bundle((changed,)),
                    digest_provider=self.digest,
                ),
            )

    def test_corrupt_semantic_authority_fails_before_qj_dispatch(self):
        _, accepted = self.r6_semantic_finding()
        context = accepted.semantic_evidence_context
        changes = (
            {"fingerprint": ""},
            {"fingerprint": "wrong"},
            {"result_id": "wrong-result"},
            {"result_fingerprint": "wrong-result-fingerprint"},
            {"variable_id": "wrong-variable"},
            {"variable_fingerprint": "wrong-variable-fingerprint"},
            {"category_code": 4},
            {"category_label": "wrong category"},
            {"question_context": "wrong question"},
            {"denominator": 1484},
            {"value": Decimal("21")},
            {"weighting_status": "WEIGHTED"},
            {"weight_set_fingerprint": "fabricated-weights"},
            {"population_description": "fabricated population"},
            {"provenance": context.provenance[:-1]},
        )
        for change in changes:
            service, generator = self.service({"proposals": []})
            with self.subTest(change=change), self.assertRaisesRegex(
                ValueError, "semantic evidence context"
            ):
                service.generate(
                    findings=(replace(
                        accepted,
                        semantic_evidence_context=replace(context, **change),
                    ),)
                )
            self.assertEqual(generator.prompts, [])

    def test_valid_synthesis_from_two_descriptive_findings(self):
        x = self.supported_single(result("x", "42", category="X"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="fx")
        y = self.supported_single(result("y", "28", category="Y"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="fy")
        proposal = insight_proposal("SYNTHESIS", "X reached 42.0% while Y reached 28.0%.", (x, y), values=("42.0", "28.0"))
        service, generator = self.service({"proposals": [proposal]})
        generated = service.generate(findings=(x, y))
        self.assertEqual(len(generator.prompts), 1)
        self.assertEqual(generated.acceptance_summary, {"proposed": 1, "parsed": 1, "accepted": 1, "rejected": 0})
        self.assertEqual(generated.accepted_insights[0].validation_status, QuantitativeInsightValidationStatus.SUPPORTED)

    def test_single_finding_synthesis_and_duplicate_support_are_rejected(self):
        _, accepted = self.r6_semantic_finding()
        proposals = [
            insight_proposal(
                "SYNTHESIS",
                "The dominant response accounted for 22.0%.",
                (accepted,),
                values=("22.0",),
            ),
            insight_proposal(
                "SYNTHESIS",
                "In the unweighted analysis, the dominant response accounted for 22.0% of valid responses.",
                (accepted,),
                values=("22.0",),
            ),
            {
                **insight_proposal(
                    "SYNTHESIS",
                    "The same Finding cannot become two independent supports.",
                    (accepted,),
                ),
                "supporting_finding_ids": [accepted.finding_id, accepted.finding_id],
            },
        ]
        service, generator = self.service({"proposals": proposals})
        generated = service.generate(findings=(accepted,))

        self.assertEqual(generated.accepted_insights, ())
        self.assertEqual(generated.acceptance_summary, {"proposed": 3, "parsed": 2, "accepted": 0, "rejected": 3})
        self.assertIn("at least two distinct accepted Findings", generated.rejected_insights[0].reason)
        self.assertIn("at least two distinct accepted Findings", generated.rejected_insights[1].reason)
        self.assertIn("unique string array", generated.rejected_insights[2].reason)
        self.assertEqual(generated.prompt_version, PROMPT_VERSION)
        self.assertIn("never restate a single descriptive Finding", generator.prompts[0])

    def test_valid_segment_contrast_and_significance_authority(self):
        a = result("a", "70", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="WOMEN")
        b = result("b", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="MEN")
        descriptive = self.supported_comparison(a, b, finding_id="descriptive")
        significant = self.supported_comparison(a, b, finding_id="significant", significant=True)
        proposals = [
            insight_proposal("SEGMENT_CONTRAST", "The observed share was higher for women.", (descriptive,), direction="HIGHER"),
            insight_proposal("SEGMENT_CONTRAST", "The share was significantly higher for women.", (significant,), direction="HIGHER"),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(descriptive, significant))
        self.assertEqual(len(generated.accepted_insights), 2)

    def test_valid_kpi_interpretation_and_limitation(self):
        kpi = self.supported_single(result("nps", "36", statistic_type="NPS", category=None), QuantitativeClaimType.KPI_VALUE, finding_id="kpi")
        proposals = [
            insight_proposal("KPI_INTERPRETATION", "The accepted NPS was 36.0.", (kpi,), values=("36.0",)),
            insight_proposal("LIMITATION", "Interpret the aggregate KPI cautiously.", (kpi,), limitation="The accepted base limits precision."),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(kpi,))
        self.assertEqual(len(generated.accepted_insights), 2)

    def test_one_finding_typed_contracts_reject_incompatible_claim_types(self):
        descriptive = self.supported_single(
            result("typed", "42"),
            QuantitativeClaimType.DESCRIPTIVE_VALUE,
            finding_id="typed-descriptive",
        )
        proposals = [
            insight_proposal("KPI_INTERPRETATION", "Interpret the accepted value.", (descriptive,)),
            insight_proposal("SEGMENT_CONTRAST", "The value was higher.", (descriptive,), direction="HIGHER"),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(descriptive,))

        self.assertEqual(generated.accepted_insights, ())
        self.assertEqual(len(generated.rejected_insights), 2)
        self.assertIn("requires an accepted KPI Finding", generated.rejected_insights[0].reason)
        self.assertIn("direction is unsupported", generated.rejected_insights[1].reason)

    def test_invented_number_and_significance_without_authority_are_rejected(self):
        descriptive = self.supported_single(result("x", "42"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="fx")
        proposals = [
            insight_proposal("SYNTHESIS", "The share was 43.0%.", (descriptive,), values=("43.0",)),
            insight_proposal("SYNTHESIS", "The result was statistically significant.", (descriptive,)),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(descriptive,))
        self.assertEqual(len(generated.rejected_insights), 2)
        self.assertEqual(len(generated.accepted_insights), 0)

    def test_incompatible_weight_filter_and_direction_are_rejected(self):
        unweighted = self.supported_single(result("u", "42"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="u")
        weighted = self.supported_single(result("w", "44", weighting="WEIGHTED", weight_fingerprint="weights"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="w")
        filtered = self.supported_single(result("f", "40", filter_definition="region=NORTH"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="f")
        a = result("a", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A")
        b = result("b", "60", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B")
        contrast = self.supported_comparison(a, b, finding_id="contrast")
        proposals = [
            insight_proposal("SYNTHESIS", "Combined weighted and unweighted pattern.", (unweighted, weighted)),
            insight_proposal("SYNTHESIS", "Combined populations.", (unweighted, filtered)),
            insight_proposal("SEGMENT_CONTRAST", "A was higher.", (contrast,), direction="HIGHER"),
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(unweighted, weighted, filtered, contrast))
        self.assertEqual(len(generated.rejected_insights), 3)

    def test_causality_pii_missing_stale_and_rejected_support_fail_closed(self):
        accepted = self.supported_single(result("x", "42"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="accepted")
        proposals = [
            insight_proposal("SYNTHESIS", "Preference drives adoption.", (accepted,)),
            insight_proposal("SYNTHESIS", "Contact alice@example.test for interpretation.", (accepted,)),
            {**insight_proposal("SYNTHESIS", "Missing support.", (accepted,)), "supporting_finding_ids": ["missing"]},
            {**insight_proposal("SYNTHESIS", "Duplicate support.", (accepted,)), "supporting_finding_ids": [accepted.finding_id, accepted.finding_id]},
        ]
        service, _ = self.service({"proposals": proposals})
        generated = service.generate(findings=(accepted,))
        self.assertEqual(len(generated.rejected_insights), 4)
        rejected = replace(accepted, support_validation_status=QuantitativeSupportStatus.UNVALIDATED)
        service, generator = self.service({"proposals": []})
        with self.assertRaisesRegex(ValueError, "rejected|stale"):
            service.generate(findings=(rejected,))
        self.assertEqual(generator.prompts, [])

    def test_deterministic_generation_and_auditable_rejection(self):
        accepted = self.supported_single(result("x", "42", category="X"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="accepted")
        second = self.supported_single(result("y", "28", category="Y"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="second")
        response = {"proposals": [
            insight_proposal("SYNTHESIS", "X reached 42.0% while Y reached 28.0%.", (accepted, second), values=("42.0", "28.0")),
            insight_proposal("SYNTHESIS", "The invented share was 99.0%.", (accepted, second), values=("99.0",)),
        ]}
        first_service, first_generator = self.service(response)
        second_service, second_generator = self.service(response)
        first = first_service.generate(findings=(accepted, second)); second_result = second_service.generate(findings=(accepted, second))
        self.assertEqual(first, second_result)
        self.assertEqual(first_generator.prompts, second_generator.prompts)
        self.assertEqual(first.accepted_insights[0].validation_version, VALIDATION_VERSION)
        self.assertEqual(first.rejected_insights[0].proposal_ordinal, 2)
        self.assertIn("99.0", str(first.rejected_insights[0].proposal_payload))
        self.assertTrue(first.rejected_insights[0].rejection_fingerprint)

    def test_prompt_and_desk_boundaries_remain_isolated(self):
        accepted = self.supported_single(result("x", "42"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="accepted")
        service, generator = self.service({"proposals": []})
        service.generate(findings=(accepted,))
        prompt = generator.prompts[0]
        self.assertIn("accepted Finding IDs", prompt)
        for forbidden in ("respondent rows", "raw DatasetVersion", "telephone", "alice@example.test"):
            self.assertNotIn(forbidden, prompt)
        import application.quantitative.insight_synthesis as module
        source = inspect.getsource(module)
        for forbidden in ("domain.findings", "domain.evidence", "get_parsed_rows", "openai", "tavily"):
            self.assertNotIn(forbidden, source)
        desk = DeskInsight("i", "p", "run", "design", "Desk insight", "implication", ("desk-finding",), "now")
        self.assertEqual(desk.finding_refs, ("desk-finding",))
        self.assertFalse(hasattr(desk, "supporting_finding_refs"))


if __name__ == "__main__":
    unittest.main()
