from __future__ import annotations

import inspect
import unittest
from copy import deepcopy
from dataclasses import replace

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import (
    QuantitativeInsightSynthesisService,
    QuantitativeInsightValidator,
)
from domain.findings.insight import Insight as DeskInsight
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeSupportStatus
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
        "supporting_finding_refs": [item.finding_id for item in supports],
        "supporting_finding_fingerprints": fingerprints or {},
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

    def test_valid_synthesis_from_two_descriptive_findings(self):
        x = self.supported_single(result("x", "42", category="X"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="fx")
        y = self.supported_single(result("y", "28", category="Y"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="fy")
        proposal = insight_proposal("SYNTHESIS", "X reached 42.0% while Y reached 28.0%.", (x, y), values=("42.0", "28.0"))
        service, generator = self.service({"proposals": [proposal]})
        generated = service.generate(findings=(x, y))
        self.assertEqual(len(generator.prompts), 1)
        self.assertEqual(generated.acceptance_summary, {"proposed": 1, "parsed": 1, "accepted": 1, "rejected": 0})
        self.assertEqual(generated.accepted_insights[0].validation_status, QuantitativeInsightValidationStatus.SUPPORTED)

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
            insight_proposal("SYNTHESIS", "Missing support.", (accepted,), fingerprints={accepted.finding_id: "stale"}),
            {**insight_proposal("SYNTHESIS", "Unknown support.", (accepted,)), "supporting_finding_refs": ["missing"]},
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
        accepted = self.supported_single(result("x", "42"), QuantitativeClaimType.DESCRIPTIVE_VALUE, finding_id="accepted")
        response = {"proposals": [
            insight_proposal("SYNTHESIS", "The accepted share was 42.0%.", (accepted,), values=("42.0",)),
            insight_proposal("SYNTHESIS", "The invented share was 99.0%.", (accepted,), values=("99.0",)),
        ]}
        first_service, first_generator = self.service(response)
        second_service, second_generator = self.service(response)
        first = first_service.generate(findings=(accepted,)); second = second_service.generate(findings=(accepted,))
        self.assertEqual(first, second)
        self.assertEqual(first_generator.prompts, second_generator.prompts)
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
