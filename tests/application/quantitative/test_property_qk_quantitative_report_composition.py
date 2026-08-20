from __future__ import annotations

import inspect
import unittest
from copy import deepcopy
from dataclasses import replace

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import QuantitativeInsightValidator
from application.quantitative.report_composition import (
    QuantitativeReportCompositionService,
    QuantitativeReportValidator,
)
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeSupportStatus
from domain.quantitative.insight import (
    QuantitativeFindingReference,
    QuantitativeInsight,
    QuantitativeInsightType,
    QuantitativeInsightValidationStatus,
)
from domain.quantitative.report import QuantitativeReportValidationStatus
from domain.reports.report import Report as DeskReport
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import (
    comparison,
    finding,
    result,
)


class FakeReportGenerator:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    @property
    def identity(self):
        return "offline-report-fake-v1"

    def generate(self, prompt):
        self.prompts.append(prompt)
        return deepcopy(self.response)


class PropertyQKQuantitativeReportCompositionTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()
        self.qh = QuantitativeFindingSupportValidator(digest_provider=self.digest)
        self.qj = QuantitativeInsightValidator(digest_provider=self.digest)

    def supported_finding(
        self,
        result_id="share",
        value="42",
        *,
        claim_type=QuantitativeClaimType.DESCRIPTIVE_VALUE,
        statistic_type="VALID_PERCENTAGE",
        category="X",
        display="42.0",
        weighting="UNWEIGHTED",
        filter_definition="ALL_ROWS",
        direction=None,
        significant=False,
    ):
        first = result(
            result_id,
            value,
            statistic_type=statistic_type,
            category=category,
            weighting=weighting,
            weight_fingerprint="weights" if weighting == "WEIGHTED" else None,
            filter_definition=filter_definition,
            column="WOMEN" if direction else None,
        )
        results = (first,)
        qg = None
        if direction:
            second = result(
                result_id + "-b",
                "20",
                statistic_type=statistic_type,
                category=category,
                weighting=weighting,
                weight_fingerprint="weights" if weighting == "WEIGHTED" else None,
                filter_definition=filter_definition,
                column="MEN",
            )
            results = (first, second)
            qg = comparison(first, second) if significant else None
        raw = finding(
            QuantitativeClaimType.SIGNIFICANT_COMPARISON if significant else claim_type,
            results,
            value=str(first.value - results[-1].value) if direction else str(first.value),
            statistic_type=statistic_type,
            category=category,
            direction=direction,
            comparison=qg,
            display_value=display,
        )
        raw = replace(raw, finding_id="finding-" + result_id)
        return self.qh.validate(
            raw,
            statistical_results={item.result_id: item for item in results},
            comparison_results={qg.comparison_result_id: qg} if qg else {},
        )

    def supported_insight(self, accepted_finding, *, kind=QuantitativeInsightType.SYNTHESIS, text="The accepted share was 42.0%."):
        raw = QuantitativeInsight(
            insight_id="insight-" + accepted_finding.finding_id,
            insight_text=text,
            insight_type=kind,
            supporting_finding_refs=(QuantitativeFindingReference(accepted_finding.finding_id, accepted_finding.support_validation_fingerprint),),
            referenced_display_values=(accepted_finding.claim.display_value,) if accepted_finding.claim.display_value and "42.0" in text else (),
            direction=accepted_finding.claim.direction,
            limitation_note="Interpret only within the accepted analytical base." if kind is QuantitativeInsightType.LIMITATION else None,
        )
        return self.qj.validate(raw, findings={accepted_finding.finding_id: accepted_finding})

    @staticmethod
    def proposal(accepted_finding, *, insight=None, section_type="KEY_FINDINGS", narrative="The accepted share was 42.0%.", values=("42.0",), direction=None, weighting=None, filter_definition=None, base_definition=None):
        insight_refs = [insight.insight_id] if insight else []
        insight_fingerprints = {insight.insight_id: insight.validation_fingerprint} if insight else {}
        section = {
            "section_id": "section-1",
            "section_type": section_type,
            "title": "Accepted results",
            "narrative": narrative,
            "finding_refs": [accepted_finding.finding_id],
            "finding_fingerprints": {accepted_finding.finding_id: accepted_finding.support_validation_fingerprint},
            "insight_refs": insight_refs,
            "insight_fingerprints": insight_fingerprints,
            "referenced_display_values": list(values),
            "authoritative_result_refs": [item.result_id for item in accepted_finding.statistical_result_refs],
            "authoritative_table_refs": [],
            "weighting_status": weighting or accepted_finding.claim.weighting_status,
            "filter_definition": filter_definition or accepted_finding.claim.filter_definition,
            "base_definition": base_definition or accepted_finding.claim.base_definition,
            "direction": direction,
        }
        return {
            "title": "Quantitative Results",
            "finding_refs": [accepted_finding.finding_id],
            "finding_fingerprints": {accepted_finding.finding_id: accepted_finding.support_validation_fingerprint},
            "insight_refs": insight_refs,
            "insight_fingerprints": insight_fingerprints,
            "sections": [section],
        }

    def compose(self, response, findings, insights=()):
        generator = FakeReportGenerator(response)
        service = QuantitativeReportCompositionService(
            generator=generator,
            validator=QuantitativeReportValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        )
        return service, generator, service.compose(findings=findings, insights=insights)

    def test_valid_report_and_executive_summary_use_accepted_support_only(self):
        accepted = self.supported_finding()
        insight = self.supported_insight(accepted)
        proposal = self.proposal(accepted, insight=insight, section_type="EXECUTIVE_SUMMARY")
        _, generator, composed = self.compose(proposal, (accepted,), (insight,))
        self.assertEqual(len(generator.prompts), 1)
        self.assertEqual(composed.accepted_report.validation_status, QuantitativeReportValidationStatus.SUPPORTED)
        self.assertEqual(composed.accepted_report.methodology, "QUANTITATIVE")
        self.assertEqual(composed.composition_metadata, {"generation_passes": 1, "repair_attempts": 0})
        self.assertNotIn("respondent", generator.prompts[0].lower())

    def test_kpi_segment_and_limitation_sections_are_supported(self):
        kpi = self.supported_finding("nps", "36", claim_type=QuantitativeClaimType.KPI_VALUE, statistic_type="NPS", category=None, display="36.0")
        segment = self.supported_finding("segment", "70", claim_type=QuantitativeClaimType.DESCRIPTIVE_COMPARISON, statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", display="50.0", direction="HIGHER")
        limitation = self.supported_finding("limited", "42")
        cases = (
            (kpi, "KPI_RESULTS", "The accepted NPS was 36.0.", ("36.0",), None),
            (segment, "SEGMENT_RESULTS", "Women had a higher observed share.", (), "HIGHER"),
            (limitation, "LIMITATIONS", "Interpret the estimate within the accepted base.", (), None),
        )
        for authority, kind, narrative, values, direction in cases:
            with self.subTest(kind=kind):
                proposal = self.proposal(authority, section_type=kind, narrative=narrative, values=values, direction=direction)
                _, _, composed = self.compose(proposal, (authority,))
                self.assertIsNotNone(composed.accepted_report)

    def test_invented_number_significance_and_causality_fail_closed(self):
        accepted = self.supported_finding()
        cases = (
            ("The accepted share was 43.0%.", ("43.0",)),
            ("The share was statistically significant.", ()),
            ("The preference drives adoption.", ()),
        )
        for narrative, values in cases:
            with self.subTest(narrative=narrative):
                _, _, composed = self.compose(self.proposal(accepted, narrative=narrative, values=values), (accepted,))
                self.assertIsNone(composed.accepted_report)
                self.assertEqual(len(composed.rejected_reports), 1)

    def test_significance_with_exact_qg_chain_is_accepted(self):
        accepted = self.supported_finding("sig", "70", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", display="50.0", direction="HIGHER", significant=True)
        proposal = self.proposal(accepted, section_type="SEGMENT_RESULTS", narrative="Women had a significantly higher share.", values=(), direction="HIGHER")
        _, _, composed = self.compose(proposal, (accepted,))
        self.assertIsNotNone(composed.accepted_report)

    def test_weight_filter_direction_and_pii_misrepresentation_fail_closed(self):
        accepted = self.supported_finding(filter_definition="region=NORTH")
        cases = (
            self.proposal(accepted, weighting="WEIGHTED"),
            self.proposal(accepted, filter_definition="region=SOUTH"),
            self.proposal(accepted, section_type="SEGMENT_RESULTS", narrative="The share was higher.", values=(), direction="HIGHER"),
            self.proposal(accepted, narrative="Contact alice@example.test for the 42.0% result."),
        )
        for proposal in cases:
            with self.subTest(proposal=proposal["sections"][0]["narrative"]):
                _, _, composed = self.compose(proposal, (accepted,))
                self.assertIsNone(composed.accepted_report)

    def test_missing_stale_and_support_outside_bundle_fail_closed(self):
        accepted = self.supported_finding()
        insight = self.supported_insight(accepted)
        cases = []
        stale = self.proposal(accepted)
        stale["finding_fingerprints"][accepted.finding_id] = "stale"
        cases.append((stale, (accepted,), ()))
        missing = self.proposal(accepted)
        missing["sections"][0]["finding_refs"] = ["missing"]
        cases.append((missing, (accepted,), ()))
        hidden_chain = self.proposal(accepted, insight=insight)
        hidden_chain["finding_refs"] = ["missing"]
        hidden_chain["finding_fingerprints"] = {"missing": "missing"}
        cases.append((hidden_chain, (accepted,), (insight,)))
        stale_insight = self.proposal(accepted, insight=insight)
        stale_insight["insight_fingerprints"][insight.insight_id] = "stale"
        cases.append((stale_insight, (accepted,), (insight,)))
        for proposal, findings, insights in cases:
            with self.subTest(proposal=proposal):
                _, _, composed = self.compose(proposal, findings, insights)
                self.assertIsNone(composed.accepted_report)

    def test_rejected_or_stale_input_never_reaches_generator(self):
        accepted = self.supported_finding()
        rejected = replace(accepted, support_validation_status=QuantitativeSupportStatus.UNVALIDATED)
        generator = FakeReportGenerator(self.proposal(accepted))
        service = QuantitativeReportCompositionService(generator=generator, validator=QuantitativeReportValidator(digest_provider=self.digest), digest_provider=self.digest)
        with self.assertRaisesRegex(ValueError, "rejected"):
            service.compose(findings=(rejected,), insights=())
        stale_insight = replace(self.supported_insight(accepted), validation_status=QuantitativeInsightValidationStatus.UNVALIDATED)
        with self.assertRaisesRegex(ValueError, "rejected"):
            service.compose(findings=(accepted,), insights=(stale_insight,))
        self.assertEqual(generator.prompts, [])

    def test_unsupported_result_table_and_desk_authority_are_rejected_or_separate(self):
        accepted = self.supported_finding()
        for key, value in (("authoritative_result_refs", ["missing-result"]), ("authoritative_table_refs", ["table-1"])):
            proposal = self.proposal(accepted)
            proposal["sections"][0][key] = value
            _, _, composed = self.compose(proposal, (accepted,))
            self.assertIsNone(composed.accepted_report)
        self.assertIn("evidence_refs", inspect.signature(DeskReport).parameters)
        self.assertNotIn("evidence_refs", inspect.signature(type(self.compose(self.proposal(accepted), (accepted,))[2].accepted_report)).parameters)

    def test_deterministic_composition_and_auditable_rejection(self):
        accepted = self.supported_finding()
        valid = self.proposal(accepted)
        first = self.compose(valid, (accepted,))[2]
        second = self.compose(valid, (accepted,))[2]
        self.assertEqual(first, second)
        invalid = self.proposal(accepted, narrative="The invented share was 99.0%.", values=("99.0",))
        rejected = self.compose(invalid, (accepted,))[2]
        self.assertEqual(rejected.proposed_report.validation_status, QuantitativeReportValidationStatus.UNVALIDATED)
        self.assertTrue(rejected.rejected_reports[0].rejection_fingerprint)

    def test_prompt_and_implementation_have_no_desk_or_external_authority(self):
        source = inspect.getsource(__import__("application.quantitative.report_composition", fromlist=["x"]))
        self.assertNotIn("domain.evidence", source)
        self.assertNotIn("domain.sources", source)
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("tavily", source.lower())


if __name__ == "__main__":
    unittest.main()
