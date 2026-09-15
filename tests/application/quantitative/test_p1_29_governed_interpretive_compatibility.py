from __future__ import annotations

from dataclasses import replace
import unittest

from application.quantitative.fingerprints import canonical_digest
from application.quantitative.insight_synthesis import QuantitativeInsightValidator
from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from domain.quantitative.insight import (
    QuantitativeFindingReference,
    QuantitativeInsight,
    QuantitativeInsightCompatibilityMode,
    QuantitativeInsightType,
)
from tests.application.quantitative.test_property_rf_insight_lineage import RecordingInsightGenerator



class P129GovernedInterpretiveCompatibilityTests(unittest.TestCase):
    def setUp(self):
        from tests.application.quantitative.test_property_rf_insight_lineage import (
            PropertyRFInsightLineageTests,
        )
        self.fixture = PropertyRFInsightLineageTests(methodName="runTest")
        self.fixture.setUp()
        self.authority = self.fixture.authority()
        self.base_finding = self.fixture.findings.accepted_findings[0]
        self.base_entry = self.authority.finding_entries[0]
        self.dimensions = {
            "project_id": self.authority.project_id,
            "run_id": self.authority.run_id,
            "dataset_version_id": "dataset-version",
            "dataset_fingerprint": "dataset-fingerprint",
            "codebook_version_id": "codebook-version",
            "codebook_fingerprint": "codebook-fingerprint",
            "analysis_family": "GROUPED_CATEGORY_DESCRIPTIVE",
            "claim_type": "DESCRIPTIVE_VALUE",
            "population_description": "authorized shared population",
            "base_definition": "VALID_RESPONSES",
            "filter_definition": "AUTHORIZED_SUBPOPULATION",
            "weighting_status": "UNWEIGHTED",
            "weight_set_fingerprint": None,
            "missing_value_semantics": "DECLARED_MISSING_EXCLUDED",
            "statistic_type": "GROUPED_CATEGORY_PERCENTAGE",
            "category_code": {"type": "string", "value": "4-5"},
            "category_label": "top-two-box agreement",
            "grouped_metric_semantic": "TOP_TWO_BOX_AGREEMENT",
            "grouped_category_members": (
                {"type": "integer", "value": "4"},
                {"type": "integer", "value": "5"},
            ),
            "grouped_category_method_version": "GROUPED_CATEGORY_V1",
        }

    def _seal(self, authority):
        payload = self.fixture.rf._input_authority_payload(
            project_id=authority.project_id,
            run_id=authority.run_id,
            generation_record_id=authority.finding_generation_record_id,
            generation_fingerprint=authority.finding_generation_fingerprint,
            re_manifest_id=authority.re_lineage_manifest_id,
            re_manifest_fingerprint=authority.re_lineage_manifest_fingerprint,
            re_input_id=authority.re_input_authority_id,
            re_input_fingerprint=authority.re_input_authority_fingerprint,
            re_coverage_id=authority.re_coverage_id,
            re_coverage_fingerprint=authority.re_coverage_fingerprint,
            rd_execution_manifest_id=authority.rd_execution_manifest_id,
            rd_execution_manifest_fingerprint=authority.rd_execution_manifest_fingerprint,
            rc_plan_id=authority.rc_plan_id,
            rc_plan_version_id=authority.rc_plan_version_id,
            rc_plan_fingerprint=authority.rc_plan_fingerprint,
            entries=authority.finding_entries,
            requirements=authority.analytical_requirement_ids,
            limitations=authority.limitations,
        )
        fingerprint = canonical_digest(payload, digest_provider=self.fixture.rf.digest)
        return replace(
            authority,
            authority_id=f"rf-input-{fingerprint}",
            fingerprint=fingerprint,
        )
    def _case(self, count=2, *, second_dimensions=None, second_branch=None):
        findings = []
        entries = []
        for index in range(count):
            finding = replace(
                self.base_finding,
                finding_id=f"finding-{index}",
                analytical_context_fingerprint=f"exact-context-{index}",
                support_validation_fingerprint=f"qh-{index}",
            )
            projection = dict(self.fixture.rf._finding_projection(finding))
            projection["analytical_context_fingerprint"] = finding.analytical_context_fingerprint
            dimensions = dict(self.dimensions)
            if index == 1 and second_dimensions:
                dimensions.update(second_dimensions)
            branch = second_branch if index == 1 and second_branch is not None else self.base_entry.branches[0]
            entry = replace(
                self.base_entry,
                finding_id=finding.finding_id,
                qh_validation_fingerprint=finding.support_validation_fingerprint,
                safe_finding_projection=projection,
                branches=(branch,),
                interpretive_context=dimensions,
                fingerprint=f"rf-entry-{index}",
            )
            findings.append(finding)
            entries.append(entry)
        authority = self._seal(replace(self.authority, finding_entries=tuple(entries)))
        insight = QuantitativeInsight(
            "insight-p1-29",
            "The supported cross-item pattern is descriptively coherent.",
            QuantitativeInsightType.SYNTHESIS,
            tuple(
                QuantitativeFindingReference(
                    item.finding_id, item.support_validation_fingerprint
                )
                for item in findings
            ),
        )
        return tuple(findings), authority, insight

    def test_cross_item_same_battery_is_governed_and_round_trip_stable(self):
        findings, authority, insight = self._case()
        governed = self.fixture.rf.compatibility_validator(authority)(insight)
        validated = QuantitativeInsightValidator(
            digest_provider=self.fixture.rc.digest
        ).validate(
            governed, findings={item.finding_id: item for item in findings},
            allow_interpretive_compatibility=True,
        )
        self.assertEqual(
            validated.compatibility_mode,
            QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value,
        )
        self.assertTrue(validated.compatibility_authority_id)
        self.assertTrue(validated.compatibility_authority_fingerprint)
        self.assertEqual(validated, decode_quantitative(encode_quantitative(validated)))

    def test_study3_shaped_four_item_synthesis_and_lineage_preserve_authority(self):
        findings, authority, _ = self._case(count=4)
        generator = RecordingInsightGenerator()
        generation = self.fixture.insight_service(generator).generate(
            findings=findings,
            post_validator=self.fixture.rf.compatibility_validator(authority),
        )
        self.assertEqual(generation.acceptance_summary["accepted"], 1)
        accepted = generation.accepted_insights[0]
        self.assertEqual(
            accepted.compatibility_mode,
            QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value,
        )
        record = f"{self.fixture.run}:p1-29:{generation.generation_fingerprint}"
        self.fixture.state.persist(
            generation,
            record_id=record,
            project_id=self.fixture.project,
            run_id=self.fixture.run,
        )
        manifest, _ = self.fixture.rf.finalize(
            authority=authority,
            generation_record_id=record,
            generation=generation,
        )
        entry = manifest.entries[0]
        self.assertEqual(entry.compatibility_mode, accepted.compatibility_mode)
        self.assertEqual(
            entry.compatibility_authority_fingerprint,
            accepted.compatibility_authority_fingerprint,
        )
        self.assertEqual(generation, decode_quantitative(encode_quantitative(generation)))
        self.assertEqual(manifest, decode_quantitative(encode_quantitative(manifest)))

    def test_interpretive_dimension_mismatch_matrix_fails_closed(self):
        cases = {
            "project": {"project_id": "other-project"},
            "run": {"run_id": "other-run"},
            "dataset": {"dataset_fingerprint": "other-dataset"},
            "codebook": {"codebook_fingerprint": "other-codebook"},
            "population": {"population_description": "other population"},
            "base": {"base_definition": "ALL_RESPONSES"},
            "filter": {"filter_definition": "OTHER_FILTER"},
            "weighting": {"weighting_status": "WEIGHTED"},
            "weight_set": {"weight_set_fingerprint": "other-weights"},
            "missing": {"missing_value_semantics": "OTHER_MISSING"},
            "analysis_family": {"analysis_family": "NUMERIC_SUMMARY"},
            "metric": {"grouped_metric_semantic": "BOTTOM_TWO_BOX"},
            "category": {"grouped_category_members": ({"type": "integer", "value": "5"},)},
            "scale": {"category_code": {"type": "string", "value": "5"}},
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                _, authority, insight = self._case(second_dimensions=change)
                with self.assertRaisesRegex(
                    Exception, "incompatible interpretive dimensions"
                ):
                    self.fixture.rf.compatibility_validator(authority)(insight)

    def test_unrelated_or_missing_battery_authority_fails_closed(self):
        branch = replace(
            self.base_entry.branches[0],
            research_question_ids=("unrelated-rq",),
            analytical_requirement_ids=("unrelated-requirement",),
        )
        _, authority, insight = self._case(second_branch=branch)
        with self.assertRaisesRegex(
            Exception, "common requirement or ResearchQuestion"
        ):
            self.fixture.rf.compatibility_validator(authority)(insight)
        _, authority, insight = self._case(second_dimensions={"claim_type": ""})
        with self.assertRaisesRegex(Exception, "descriptive Findings"):
            self.fixture.rf.compatibility_validator(authority)(insight)

    def test_stale_and_predeclared_compatibility_authority_fail_closed(self):
        _, authority, insight = self._case()
        with self.assertRaisesRegex(Exception, "stale or malformed RF input authority"):
            self.fixture.rf.compatibility_validator(
                replace(authority, fingerprint="stale")
            )
        resolver = self.fixture.rf.compatibility_validator(authority)
        with self.assertRaisesRegex(Exception, "predeclared compatibility authority"):
            resolver(replace(
                insight,
                compatibility_mode=(
                    QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value
                ),
                compatibility_authority_id="provider-authored",
                compatibility_authority_fingerprint="provider-authored",
            ))
    def test_cross_item_inference_and_causality_remain_rejected(self):
        findings, authority, insight = self._case()
        validator = QuantitativeInsightValidator(digest_provider=self.fixture.rc.digest)
        governed = self.fixture.rf.compatibility_validator(authority)(insight)
        for text in (
            "The first item was statistically significantly higher.",
            "Capability drives innovation tracking.",
        ):
            with self.subTest(text=text), self.assertRaises(Exception):
                validator.validate(
                    replace(governed, insight_text=text),
                    findings={item.finding_id: item for item in findings},
                )

    def test_exact_context_validation_fingerprint_preserves_qj2_contract(self):
        findings, _, insight = self._case()
        common_context = findings[0].analytical_context_fingerprint
        findings = (
            findings[0],
            replace(findings[1], analytical_context_fingerprint=common_context),
        )
        validated = QuantitativeInsightValidator(
            digest_provider=self.fixture.rc.digest
        ).validate(insight, findings={item.finding_id: item for item in findings})
        expected = canonical_digest(
            {
                "insight_id": insight.insight_id,
                "type": insight.insight_type.value,
                "text": insight.insight_text,
                "supports": tuple(
                    (item.finding_id, item.support_validation_fingerprint)
                    for item in findings
                ),
                "referenced_display_values": insight.referenced_display_values,
                "direction": insight.direction,
                "limitation_note": insight.limitation_note,
                "context": common_context,
                "version": "qj-2",
            },
            digest_provider=self.fixture.rc.digest,
        )
        self.assertEqual(validated.validation_version, "qj-2")
        self.assertEqual(validated.validation_fingerprint, expected)
        self.assertEqual(validated.support_context_fingerprint, common_context)

if __name__ == "__main__":
    unittest.main()
