import json
from dataclasses import replace

from application.quantitative.report_composition import QuantitativeReportCompositionService
from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from tests.application.quantitative import (
    test_p1_35_deterministic_governed_report_composition as p135,
)


class TestP138SystemDerivedQK3ClaimEvidence:
    def setup_method(self):
        self._fixture = p135.TestP135DeterministicGovernedReportComposition()
        self._fixture.setUp()

    def __getattr__(self, name):
        fixture = self.__dict__.get("_fixture")
        if fixture is None:
            raise AttributeError(name)
        return getattr(fixture, name)

    def test_provider_schema_excludes_system_owned_claim_evidence(self):
        prompt = QuantitativeReportCompositionService._prompt_v3({"findings": [], "insights": []})
        schema = json.loads(
            prompt.split("\nOUTPUT_SCHEMA=", 1)[1].split("\nAPPROVED_SUPPORT=", 1)[0]
        )
        fields = set(schema["sections"][0]["claim_units"][0])
        assert fields == {
            "claim_id",
            "text",
            "support_mode",
            "finding_refs",
            "insight_refs",
        }

    def test_provider_injected_claim_evidence_fails_closed(self):
        finding = self.supported_finding()
        for field, value in (
            ("authoritative_result_refs", ["provider-owned-result"]),
            ("referenced_display_values", ["999.0"]),
        ):
            unit = self.unit("direct", finding.text, "DIRECT_FINDING", (finding,))
            unit[field] = value
            result = self.compose_v3(self.proposal_v3(unit), (finding,))[2]
            assert result.accepted_report is None
            assert "unsupported fields" in result.rejected_reports[0].reason

    def test_direct_evidence_is_derived_from_persisted_finding(self):
        finding = self.supported_finding("canonical-result", "42", display="42.0")
        result = self.compose_v3(
            self.proposal_v3(self.unit("direct", finding.text, "DIRECT_FINDING", (finding,))),
            (finding,),
        )[2]
        claim = result.accepted_report.sections[0].claim_units[0]
        assert claim.referenced_display_values == ("42.0",)
        assert claim.authoritative_result_refs == ("canonical-result",)

    def test_relational_evidence_uses_persisted_insight_support_order(self):
        first = self.supported_finding("result-a", "42", display="42.0")
        second = self.supported_finding("result-b", "28", display="28.0")
        insight = self.governed_insight((first, second))
        unit = self.unit(
            "relation",
            insight.insight_text,
            "INTERPRETIVE_COMPATIBILITY_INSIGHT",
            (second, first),
            (insight,),
        )
        result = self.compose_v3(self.proposal_v3(unit), (first, second), (insight,))[2]
        claim = result.accepted_report.sections[0].claim_units[0]
        assert tuple(ref.authority_id for ref in claim.finding_refs) == (
            first.finding_id,
            second.finding_id,
        )
        assert claim.referenced_display_values == insight.referenced_display_values
        assert claim.authoritative_result_refs == ("result-a", "result-b")

    def test_realistic_semantic_only_proposal_roundtrips_stably(self):
        first = self.supported_finding("result-a", "42", display="42.0")
        second = self.supported_finding("result-b", "28", display="28.0")
        insight = self.governed_insight((first, second), exact=True)
        response = self.proposal_v3(
            self.unit("direct", first.text, "DIRECT_FINDING", (first,)),
            self.unit("relation", insight.insight_text, "EXACT_CONTEXT_INSIGHT", (first, second), (insight,)),
        )
        report = self.compose_v3(response, (first, second), (insight,))[2].accepted_report
        restored = decode_quantitative(encode_quantitative(report))
        assert restored == report
        assert restored.validation_fingerprint == report.validation_fingerprint
        assert report.generation_metadata["prompt_version"] == "QK_REPORT_COMPOSITION_V4"
        assert report.generation_version == "qk-3"

    def test_p1_36_shaped_nine_claim_replay_derives_exact_result_refs(self):
        finding_specs = (
            ("ability", "f6b99f1f-82b2-5e51-b661-05a5a4a1a342", "77.8"),
            ("saving", "3ed6d009-5dfc-5540-a60d-7ab6165c8be1", "77.2"),
            ("comfort", "69842a4b-fa37-5562-a652-9bf163ae2ee6", "77.0"),
            ("saving-fully", "e495ef79-31dd-5d82-93dd-fde8fba0af38", "51.8"),
            ("ability-fully", "dfd44b89-df93-53e4-b53a-2fda2383c115", "53.6"),
            ("identity-fully", "284c88ac-f02b-57cd-94ec-7ce7bd8d69e2", "32.0"),
            ("innovation-fully", "4f229a32-0d18-5ce1-a74a-e1e45c4cfd3f", "24.3"),
            ("innovation", "e8bc905a-461b-59ea-a56b-8693d2553db5", "42.1"),
            ("identity", "6d9933ea-0359-5d34-9fbb-e3f241c96066", "52.2"),
            ("comfort-fully", "158b42f3-ec66-5dcb-b0bb-e190b7295e11", "49.4"),
        )
        findings = {
            name: self.supported_finding(result_id, display, display=display)
            for name, result_id, display in finding_specs
        }
        insight_one = replace(
            self.governed_insight((findings["ability"], findings["saving"], findings["comfort"])),
            insight_id="p1-36-insight-one",
        )
        insight_two = replace(
            self.governed_insight((findings["identity"], findings["ability"])),
            insight_id="p1-36-insight-two",
        )
        insight_three = replace(
            self.governed_insight((findings["saving"], findings["comfort"], findings["innovation"])),
            insight_id="p1-36-insight-three",
        )
        sections = (
            ("sec_exec_001", "EXECUTIVE_SUMMARY", (
                self.unit("clm_ins_001", insight_one.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (findings["ability"], findings["saving"], findings["comfort"]), (insight_one,)),
            )),
            ("sec_key_001", "KEY_FINDINGS", (
                self.unit("clm_ins_002", insight_two.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (findings["ability"], findings["identity"]), (insight_two,)),
                self.unit("clm_ins_003", insight_three.insight_text, "INTERPRETIVE_COMPATIBILITY_INSIGHT", (findings["innovation"], findings["comfort"], findings["saving"]), (insight_three,)),
            )),
            ("sec_kpi_001", "KPI_RESULTS", (
                self.unit("clm_fnd_001", findings["ability-fully"].text, "DIRECT_FINDING", (findings["ability-fully"],)),
                self.unit("clm_fnd_002", findings["saving"].text, "DIRECT_FINDING", (findings["saving"],)),
                self.unit("clm_fnd_003", findings["comfort-fully"].text, "DIRECT_FINDING", (findings["comfort-fully"],)),
            )),
            ("sec_seg_001", "SEGMENT_RESULTS", (
                self.unit("clm_fnd_004", findings["innovation"].text, "DIRECT_FINDING", (findings["innovation"],)),
                self.unit("clm_fnd_005", findings["identity-fully"].text, "DIRECT_FINDING", (findings["identity-fully"],)),
                self.unit("clm_fnd_006", findings["innovation-fully"].text, "DIRECT_FINDING", (findings["innovation-fully"],)),
            )),
        )
        response = {
            "title": "P1-36 shaped report",
            "sections": [
                {
                    "section_id": section_id,
                    "section_type": section_type,
                    "title": section_id,
                    "claim_units": list(units),
                }
                for section_id, section_type, units in sections
            ],
        }
        result = self.compose_v3(
            response,
            tuple(findings.values()),
            (insight_one, insight_two, insight_three),
        )[2]
        assert result.accepted_report is not None
        actual = {
            unit.claim_id: unit.authoritative_result_refs
            for section in result.accepted_report.sections
            for unit in section.claim_units
        }
        assert actual == {
            "clm_ins_001": (
                "f6b99f1f-82b2-5e51-b661-05a5a4a1a342",
                "3ed6d009-5dfc-5540-a60d-7ab6165c8be1",
                "69842a4b-fa37-5562-a652-9bf163ae2ee6",
            ),
            "clm_ins_002": (
                "6d9933ea-0359-5d34-9fbb-e3f241c96066",
                "f6b99f1f-82b2-5e51-b661-05a5a4a1a342",
            ),
            "clm_ins_003": (
                "3ed6d009-5dfc-5540-a60d-7ab6165c8be1",
                "69842a4b-fa37-5562-a652-9bf163ae2ee6",
                "e8bc905a-461b-59ea-a56b-8693d2553db5",
            ),
            "clm_fnd_001": ("dfd44b89-df93-53e4-b53a-2fda2383c115",),
            "clm_fnd_002": ("3ed6d009-5dfc-5540-a60d-7ab6165c8be1",),
            "clm_fnd_003": ("158b42f3-ec66-5dcb-b0bb-e190b7295e11",),
            "clm_fnd_004": ("e8bc905a-461b-59ea-a56b-8693d2553db5",),
            "clm_fnd_005": ("284c88ac-f02b-57cd-94ec-7ce7bd8d69e2",),
            "clm_fnd_006": ("4f229a32-0d18-5ce1-a74a-e1e45c4cfd3f",),
        }