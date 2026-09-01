from __future__ import annotations

from dataclasses import replace
import unittest

from application.quantitative.insight_lineage import (
    QuantitativeInsightLineageError,
)
from application.quantitative.report_lineage import (
    QuantitativeReportLineageError,
    QuantitativeReportLineageService,
)
from domain.quantitative.insight_lineage import (
    DesignAwareInsightAbsenceReason,
    DesignAwareInsightControlledAbsence,
)
from domain.quantitative.report_lineage import (
    DesignAwareReportAbsenceReason,
    DesignAwareReportControlledAbsence,
)
from infrastructure.persistence.quantitative_report_lineage_repository import (
    QLQuantitativeReportLineageRepository,
)
from tests.application.quantitative.test_property_rf_insight_lineage import (
    PropertyRFInsightLineageTests,
)


class RejectingFindingGenerator:
    identity = "q2-13-rejecting-finding-v1"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return {
            "proposals": [{
                "claim_type": "DESCRIPTIVE_VALUE",
                "finding_text": "Unsupported deterministic proposal.",
                "statistical_result_refs": ["not-in-bundle"],
                "comparison_result_refs": [],
                "value": 1,
                "display_value": "1",
                "rounding_decimal_places": 1,
                "variable_id": "unknown",
                "statistic_type": "VALID_PERCENTAGE",
                "category_value": "unknown",
                "filter_definition": None,
                "base_definition": "VALID",
                "weighting_status": "UNWEIGHTED",
                "weight_set_fingerprint": None,
                "direction": None,
                "limitation_note": None,
            }],
        }


class Q213DesignAwareControlledAbsenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PropertyRFInsightLineageTests(methodName="runTest")
        self.fixture.setUp()
        self.rg_repository = QLQuantitativeReportLineageRepository(
            self.fixture.state
        )
        self.rg = QuantitativeReportLineageService(
            repository=self.rg_repository,
            digest_provider=self.fixture.rc.digest,
        )

    def _zero_finding_authority(self):
        generator = RejectingFindingGenerator()
        service = self.fixture.re_fixture.finding_service(generator)
        results, comparisons = self.fixture.lineage.load_results(
            self.fixture.re_input
        )
        generation = service.generate(
            statistical_results=results,
            comparison_results=comparisons,
            limitations=self.fixture.lineage.generation_limitations(
                self.fixture.re_input
            ),
        )
        self.assertEqual(generation.accepted_findings, ())
        self.assertEqual(len(generation.rejected_findings), 1)
        record_id = (
            f"{self.fixture.run}:finding-generation:"
            f"{generation.generation_fingerprint}"
        )
        self.fixture.state.persist(
            generation, record_id=record_id, project_id=self.fixture.project,
            run_id=self.fixture.run,
        )
        manifest, coverage = self.fixture.lineage.finalize(
            authority=self.fixture.re_input,
            generation_record_id=record_id,
            generation=generation,
        )
        return generation, record_id, manifest, coverage

    def test_typed_rf_rg_absence_is_deterministic_restart_safe_and_exact(self):
        generation, record_id, re_manifest, re_coverage = (
            self._zero_finding_authority()
        )
        kwargs = dict(
            project_id=self.fixture.project,
            run_id=self.fixture.run,
            generation_record_id=record_id,
            generation=generation,
            re_input=self.fixture.re_input,
            re_manifest=re_manifest,
            re_coverage=re_coverage,
        )
        rf_first = self.fixture.rf.design_aware_controlled_absence(**kwargs)
        rf_second = self.fixture.rf.design_aware_controlled_absence(**kwargs)
        self.assertEqual(rf_first, rf_second)
        self.assertEqual(
            DesignAwareInsightAbsenceReason.NO_SUPPORTED_FINDINGS,
            rf_first.reason,
        )
        self.assertEqual(
            rf_first,
            self.fixture.state.load(
                rf_first.absence_id,
                project_id=self.fixture.project,
                expected_type=DesignAwareInsightControlledAbsence,
            ),
        )

        rg_kwargs = dict(
            project_id=self.fixture.project,
            run_id=self.fixture.run,
            generation_record_id=record_id,
            generation=generation,
            rf_absence=rf_first,
            re_manifest=re_manifest,
        )
        rg_first = self.rg.design_aware_controlled_absence(**rg_kwargs)
        rg_second = self.rg.design_aware_controlled_absence(**rg_kwargs)
        self.assertEqual(rg_first, rg_second)
        self.assertEqual(
            DesignAwareReportAbsenceReason.NO_SUPPORTED_FINDINGS,
            rg_first.reason,
        )
        self.assertEqual(
            rg_first,
            self.fixture.state.load(
                rg_first.absence_id,
                project_id=self.fixture.project,
                expected_type=DesignAwareReportControlledAbsence,
            ),
        )
        self.assertEqual(rg_first.rf_absence_id, rf_first.absence_id)
        self.assertNotIn("respondent", repr((rf_first, rg_first)).lower())

    def test_wrong_scope_stale_lineage_and_supported_findings_fail_closed(self):
        generation, record_id, re_manifest, re_coverage = (
            self._zero_finding_authority()
        )
        base = dict(
            project_id=self.fixture.project,
            run_id=self.fixture.run,
            generation_record_id=record_id,
            generation=generation,
            re_input=self.fixture.re_input,
            re_manifest=re_manifest,
            re_coverage=re_coverage,
        )
        for change in (
            {"project_id": "wrong-project"},
            {"run_id": "wrong-run"},
            {"re_manifest": replace(
                re_manifest, input_authority_fingerprint="stale"
            )},
            {"re_coverage": replace(re_coverage, fingerprint="stale")},
        ):
            with self.subTest(change=change), self.assertRaises(
                QuantitativeInsightLineageError
            ):
                self.fixture.rf.design_aware_controlled_absence(
                    **(base | change)
                )
        with self.assertRaisesRegex(
            QuantitativeInsightLineageError, "contradicts accepted"
        ):
            self.fixture.rf.design_aware_controlled_absence(
                **(base | {
                    "generation_record_id": self.fixture.finding_record,
                    "generation": self.fixture.findings,
                    "re_manifest": self.fixture.re_manifest,
                    "re_coverage": self.fixture.re_coverage,
                })
            )

        rf_absence = self.fixture.rf.design_aware_controlled_absence(**base)
        with self.assertRaises(QuantitativeReportLineageError):
            self.rg.design_aware_controlled_absence(
                project_id=self.fixture.project,
                run_id=self.fixture.run,
                generation_record_id=record_id,
                generation=generation,
                rf_absence=replace(
                    rf_absence, re_lineage_manifest_fingerprint="stale"
                ),
                re_manifest=re_manifest,
            )

    def test_production_vertical_persists_absences_without_qj_or_qk(self):
        generation, record_id, re_manifest, re_coverage = (
            self._zero_finding_authority()
        )
        vertical = self.fixture.re_fixture._vertical(
            RejectingFindingGenerator()
        )
        vertical.insight_lineage = self.fixture.rf
        vertical.report_lineage = self.rg
        state = self.fixture.re_fixture._safe_state()
        state.update({
            "finding_generation_record_id": record_id,
            "finding_input_authority_record_id": self.fixture.re_input.authority_id,
            "finding_lineage_manifest_record_id": re_manifest.manifest_id,
            "finding_coverage_manifest_record_id": re_coverage.coverage_id,
            "zero_supported_findings": "true",
        })
        state = vertical._quant_insights(
            self.fixture.project, self.fixture.run, state
        )
        state = vertical._quant_report(
            self.fixture.project, self.fixture.run, state
        )
        rf_id = state["insight_controlled_absence_record_id"]
        rg_id = state["report_controlled_absence_record_id"]
        replay = vertical._quant_insights(
            self.fixture.project, self.fixture.run, dict(state)
        )
        replay = vertical._quant_report(
            self.fixture.project, self.fixture.run, replay
        )
        self.assertEqual(rf_id, replay["insight_controlled_absence_record_id"])
        self.assertEqual(rg_id, replay["report_controlled_absence_record_id"])
        self.assertNotIn("insight_generation_record_id", state)
        self.assertNotIn("report_composition_record_id", state)


if __name__ == "__main__":
    unittest.main()
