from copy import deepcopy
from dataclasses import replace

from application.quantitative.report_composition import (
    QuantitativeReportCompositionService,
    QuantitativeReportValidator,
)
from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from domain.quantitative.insight import (
    QuantitativeFindingReference,
    QuantitativeInsight,
    QuantitativeInsightCompatibilityMode,
    QuantitativeInsightType,
)
from tests.application.quantitative.test_property_qk_quantitative_report_composition import (
    FakeReportGenerator,
    PropertyQKQuantitativeReportCompositionTests,
)


class TestP135DeterministicGovernedReportComposition(PropertyQKQuantitativeReportCompositionTests):
    def service(self, response):
        generator = FakeReportGenerator(response)
        service = QuantitativeReportCompositionService(
            generator=generator,
            validator=QuantitativeReportValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        )
        return service, generator

    @staticmethod
    def bundle(service, findings, insights=()):
        return {
            "findings": tuple(service._finding_projection(item) for item in sorted(findings, key=lambda item: item.finding_id)),
            "insights": tuple(service._insight_projection(item) for item in sorted(insights, key=lambda item: item.insight_id)),
        }

    @staticmethod
    def unit(claim_id, text, mode, findings, insights=()):
        return {
            "claim_id": claim_id,
            "text": text,
            "support_mode": mode,
            "finding_refs": [item.finding_id for item in findings],
            "insight_refs": [item.insight_id for item in insights],
        }

    @staticmethod
    def proposal_v3(*units):
        return {
            "title": "Quantitative Results",
            "sections": [{
                "section_id": "section-1",
                "section_type": "KEY_FINDINGS",
                "title": "Governed claims",
                "claim_units": list(units),
            }],
        }

    def governed_insight(self, findings, *, exact=False):
        mode = (
            QuantitativeInsightCompatibilityMode.EXACT_CONTEXT.value
            if exact
            else QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value
        )
        raw = QuantitativeInsight(
            "insight-governed",
            "The governed values were " + " and ".join(item.claim.display_value + "%" for item in findings) + ".",
            QuantitativeInsightType.SYNTHESIS,
            tuple(QuantitativeFindingReference(item.finding_id, item.support_validation_fingerprint) for item in findings),
            tuple(item.claim.display_value for item in findings),
            compatibility_mode=mode,
            compatibility_authority_id=None if exact else "compatibility-authority",
            compatibility_authority_fingerprint=None if exact else "compatibility-fingerprint",
        )
        accepted = self.qj.validate(
            raw,
            findings={item.finding_id: item for item in findings},
            allow_interpretive_compatibility=not exact,
        )
        if exact:
            return accepted
        return replace(
            accepted,
            compatibility_mode=mode,
            compatibility_authority_id="compatibility-authority",
            compatibility_authority_fingerprint="compatibility-fingerprint",
        )

    def compose_v3(self, response, findings, insights=()):
        service, generator = self.service(response)
        result = service.compose_design_aware(
            findings=findings,
            insights=insights,
            bundle=self.bundle(service, findings, insights),
        )
        return service, generator, result

    def test_direct_claims_derive_narrative_context_and_report_support(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        response = self.proposal_v3(
            self.unit("first", first.text, "DIRECT_FINDING", (first,)),
            self.unit("second", second.text, "DIRECT_FINDING", (second,)),
        )
        _, generator, composed = self.compose_v3(response, (first, second))
        report = composed.accepted_report
        assert report is not None
        assert report.generation_version == "qk-3"
        assert report.sections[0].narrative == first.text.strip() + " " + second.text.strip()
        assert report.sections[0].weighting_status == first.claim.weighting_status
        assert report.sections[0].filter_definition == first.claim.filter_definition
        assert report.sections[0].base_definition == first.claim.base_definition
        assert tuple(ref.authority_id for ref in report.supporting_finding_refs) == (first.finding_id, second.finding_id)
        assert "section narrative" in generator.prompts[0]
        assert '"narrative"' not in generator.prompts[0].split("APPROVED_SUPPORT=", 1)[0]

    def test_deterministic_separator_identity_and_fingerprint(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        response = self.proposal_v3(
            self.unit("first", first.text, "DIRECT_FINDING", (first,)),
            self.unit("second", second.text, "DIRECT_FINDING", (second,)),
        )
        first_result = self.compose_v3(response, (first, second))[2]
        second_result = self.compose_v3(deepcopy(response), (first, second))[2]
        assert first_result == second_result
        assert first_result.accepted_report.validation_fingerprint == second_result.accepted_report.validation_fingerprint

    def test_exact_context_insight_claim_is_accepted(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        insight = self.governed_insight((first, second), exact=True)
        response = self.proposal_v3(self.unit("relation", insight.insight_text, "EXACT_CONTEXT_INSIGHT", (first, second), (insight,)))
        report = self.compose_v3(response, (first, second), (insight,))[2].accepted_report
        assert report is not None
        assert report.sections[0].narrative == insight.insight_text

    def test_interpretive_insight_plus_independent_direct_claim_is_accepted(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        third = self.supported_finding("third", "17", display="17.0")
        insight = self.governed_insight((first, second))
        response = self.proposal_v3(
            self.unit("relation", insight.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first, second), (insight,)),
            self.unit("third", third.text, "DIRECT_FINDING", (third,)),
        )
        report = self.compose_v3(response, (first, second, third), (insight,))[2].accepted_report
        assert report is not None
        assert report.sections[0].narrative == insight.insight_text + " " + third.text

    def test_provider_cannot_author_system_owned_section_fields(self):
        finding = self.supported_finding()
        response = self.proposal_v3(self.unit("direct", finding.text, "DIRECT_FINDING", (finding,)))
        response["sections"][0]["narrative"] = finding.text
        rejected = self.compose_v3(response, (finding,))[2]
        assert rejected.accepted_report is None
        assert "system-owned section fields" in rejected.rejected_reports[0].reason

    def test_unsupported_or_empty_methodology_section_is_rejected(self):
        finding = self.supported_finding()
        response = {"title": "Report", "sections": [{"section_id": "method", "section_type": "LIMITATIONS", "title": "Method", "claim_units": []}]}
        rejected = self.compose_v3(response, (finding,))[2]
        assert rejected.accepted_report is None

    def test_direct_claim_cannot_use_multiple_findings_or_insight(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        insight = self.governed_insight((first, second))
        cases = (
            self.unit("many", first.text, "DIRECT_FINDING", (first, second)),
            self.unit("insight", first.text, "DIRECT_FINDING", (first,), (insight,)),
        )
        for unit in cases:
            result = self.compose_v3(self.proposal_v3(unit), (first, second), (insight,))[2]
            assert result.accepted_report is None

    def test_insight_claim_requires_exact_text_and_complete_support(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        insight = self.governed_insight((first, second))
        altered = self.unit("altered", insight.insight_text + " altered", "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first, second), (insight,))
        incomplete = self.unit("incomplete", insight.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first,), (insight,))
        for unit in (altered, incomplete):
            result = self.compose_v3(self.proposal_v3(unit), (first, second), (insight,))[2]
            assert result.accepted_report is None

    def test_unused_support_is_not_representable_in_qk3_and_bundle_order_is_enforced(self):
        first = self.supported_finding("first", "42", display="42.0")
        second = self.supported_finding("second", "28", display="28.0")
        response = self.proposal_v3(self.unit("first", first.text, "DIRECT_FINDING", (first,)))
        result = self.compose_v3(response, (first, second))[2]
        assert result.accepted_report is not None
        assert tuple(ref.authority_id for ref in result.accepted_report.supporting_finding_refs) == (first.finding_id,)

    def test_transitive_compatibility_cannot_be_manufactured(self):
        first = self.supported_finding("first", "42", display="42.0")
        middle = self.supported_finding("middle", "28", display="28.0")
        third = self.supported_finding("third", "17", display="17.0")
        i12 = self.governed_insight((first, middle))
        i23 = replace(self.governed_insight((middle, third)), insight_id="insight-second")
        unit = self.unit("transitive", i12.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (first, third), (i12, i23))
        result = self.compose_v3(self.proposal_v3(unit), (first, middle, third), (i12, i23))[2]
        assert result.accepted_report is None

    def test_qk3_serialization_roundtrip_preserves_derived_fingerprint(self):
        finding = self.supported_finding()
        response = self.proposal_v3(self.unit("direct", finding.text, "DIRECT_FINDING", (finding,)))
        report = self.compose_v3(response, (finding,))[2].accepted_report
        restored = decode_quantitative(encode_quantitative(report))
        assert restored == report
        assert restored.validation_fingerprint == report.validation_fingerprint
        assert restored.generation_version == "qk-3"

    def test_legacy_qk1_and_historical_qk2_remain_unchanged(self):
        finding = self.supported_finding()
        qk1 = self.compose(PropertyQKQuantitativeReportCompositionTests.proposal(finding), (finding,))[2].accepted_report
        assert qk1.generation_version == "qk-1"
        qk2_response = PropertyQKQuantitativeReportCompositionTests.proposal(finding)
        qk2_unit = self.unit("legacy", qk2_response["sections"][0]["narrative"], "DIRECT_FINDING", (finding,))
        qk2_unit["referenced_display_values"] = [finding.claim.display_value]
        qk2_unit["authoritative_result_refs"] = [ref.result_id for ref in finding.statistical_result_refs]
        qk2_response["sections"][0]["claim_units"] = [qk2_unit]
        qk2 = self.compose(qk2_response, (finding,))[2].accepted_report
        assert qk2.generation_version == "qk-2"
        assert decode_quantitative(encode_quantitative(qk2)) == qk2