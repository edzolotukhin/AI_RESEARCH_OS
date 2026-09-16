from copy import deepcopy
from dataclasses import replace

from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from domain.quantitative.insight import (
    QuantitativeFindingReference,
    QuantitativeInsight,
    QuantitativeInsightCompatibilityMode,
    QuantitativeInsightType,
)
from tests.application.quantitative.test_property_qk_quantitative_report_composition import (
    PropertyQKQuantitativeReportCompositionTests,
)


class TestP132GovernedClauseReportComposition(PropertyQKQuantitativeReportCompositionTests):
    def governed(self, insight_id, findings):
        raw = QuantitativeInsight(
            insight_id,
            "Governed relationship across accepted findings.",
            QuantitativeInsightType.SYNTHESIS,
            tuple(QuantitativeFindingReference(item.finding_id, item.support_validation_fingerprint) for item in findings),
            tuple(item.claim.display_value for item in findings),
            compatibility_mode=QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value,
            compatibility_authority_id="qj-compat-" + insight_id,
            compatibility_authority_fingerprint="authority-" + insight_id,
        )
        accepted = self.qj.validate(raw, findings={item.finding_id: item for item in findings}, allow_interpretive_compatibility=True)
        return replace(accepted, compatibility_mode=QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value, compatibility_authority_id="qj-compat-" + insight_id, compatibility_authority_fingerprint="authority-" + insight_id)

    @staticmethod
    def unit(claim_id, text, mode, findings, insights=()):
        return {
            "claim_id": claim_id,
            "text": text,
            "support_mode": mode,
            "finding_refs": [item.finding_id for item in findings],
            "insight_refs": [item.insight_id for item in insights],
            "referenced_display_values": [item.claim.display_value for item in findings if item.claim.display_value],
            "authoritative_result_refs": [ref.result_id for item in findings for ref in item.statistical_result_refs],
        }

    def mixed_proposal(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        extra = self.supported_finding("extra", "17", display="17.0")
        insight = self.governed("first-second", (first, second))
        relation = "The accepted values were 42.0% and 28.0%."
        direct = " Separately, the accepted extra result was 17.0%."
        proposal = self.proposal(first, insight=insight, narrative=relation + direct, values=("42.0", "28.0", "17.0"))
        findings = (first, second, extra)
        proposal["finding_refs"] = [item.finding_id for item in findings]
        proposal["finding_fingerprints"] = {item.finding_id: item.support_validation_fingerprint for item in findings}
        section = proposal["sections"][0]
        section["finding_refs"] = list(proposal["finding_refs"])
        section["finding_fingerprints"] = dict(proposal["finding_fingerprints"])
        section["authoritative_result_refs"] = [ref.result_id for item in findings for ref in item.statistical_result_refs]
        section["claim_units"] = [
            self.unit("relationship", relation, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first, second), (insight,)),
            self.unit("independent", direct, "DIRECT_FINDING", (extra,)),
        ]
        return proposal, findings, insight

    def test_governed_relationship_and_independent_direct_claim_coexist(self):
        proposal, findings, insight = self.mixed_proposal()
        composed = self.compose(proposal, findings, (insight,))[2]
        assert composed.accepted_report is not None
        assert composed.accepted_report.generation_version == "qk-2"
        assert len(composed.accepted_report.sections[0].claim_units) == 2

    def test_claim_units_are_deterministic_and_exactly_partition_narrative(self):
        proposal, findings, insight = self.mixed_proposal()
        first = self.compose(proposal, findings, (insight,))[2]
        second = self.compose(deepcopy(proposal), findings, (insight,))[2]
        assert first == second
        proposal["sections"][0]["claim_units"][1]["text"] += " altered"
        rejected = self.compose(proposal, findings, (insight,))[2]
        assert rejected.accepted_report is None
        assert "exactly partition" in rejected.rejected_reports[0].reason

    def test_uncovered_cross_context_relationship_remains_rejected(self):
        proposal, findings, insight = self.mixed_proposal()
        extra = findings[2]
        relationship = proposal["sections"][0]["claim_units"][0]
        relationship["text"] += proposal["sections"][0]["claim_units"][1]["text"]
        relationship["finding_refs"].append(extra.finding_id)
        relationship["referenced_display_values"].append(extra.claim.display_value)
        relationship["authoritative_result_refs"].append(extra.statistical_result_refs[0].result_id)
        proposal["sections"][0]["claim_units"] = [relationship]
        rejected = self.compose(proposal, findings, (insight,))[2]
        assert rejected.accepted_report is None
        assert "complete governed Insight authority" in rejected.rejected_reports[0].reason

    def test_transitive_compatibility_is_not_inferred(self):
        first = self.supported_finding("first", "42", display="42.0")
        middle = self.supported_finding("middle", "28", display="28.0")
        third = self.supported_finding("third", "17", display="17.0")
        i12 = self.governed("i12", (first, middle))
        i23 = self.governed("i23", (middle, third))
        text = "The first value 42.0% was related to the third value 17.0%."
        proposal = self.proposal(first, insight=i12, narrative=text, values=("42.0", "17.0"))
        findings = (first, middle, third)
        proposal["finding_refs"] = [item.finding_id for item in findings]
        proposal["finding_fingerprints"] = {item.finding_id: item.support_validation_fingerprint for item in findings}
        proposal["insight_refs"] = [i12.insight_id, i23.insight_id]
        proposal["insight_fingerprints"] = {item.insight_id: item.validation_fingerprint for item in (i12, i23)}
        section = proposal["sections"][0]
        section["finding_refs"] = [first.finding_id, third.finding_id]
        section["finding_fingerprints"] = {item.finding_id: item.support_validation_fingerprint for item in (first, third)}
        section["insight_refs"] = [i12.insight_id, i23.insight_id]
        section["insight_fingerprints"] = dict(proposal["insight_fingerprints"])
        section["authoritative_result_refs"] = [first.statistical_result_refs[0].result_id, third.statistical_result_refs[0].result_id]
        section["claim_units"] = [self.unit("unsafe-transitive", text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first, third), (i12, i23))]
        rejected = self.compose(proposal, findings, (i12, i23))[2]
        assert rejected.accepted_report is None
        assert "complete governed Insight authority" in rejected.rejected_reports[0].reason

    def test_claim_units_round_trip_through_quantitative_encoding(self):
        proposal, findings, insight = self.mixed_proposal()
        report = self.compose(proposal, findings, (insight,))[2].accepted_report
        restored = decode_quantitative(encode_quantitative(report))
        assert restored == report
        assert restored.validation_fingerprint == report.validation_fingerprint
    def test_legacy_report_fingerprint_path_remains_qk_1(self):
        accepted = self.supported_finding()
        composed = self.compose(self.proposal(accepted), (accepted,))[2]
        assert composed.accepted_report is not None
        assert composed.accepted_report.generation_version == "qk-1"
        assert composed.accepted_report.sections[0].claim_units == ()
