from __future__ import annotations

from dataclasses import replace
import json
import unittest

from application.quantitative.insight_synthesis import (
    QuantitativeInsightSynthesisService,
    QuantitativeInsightValidator,
)
from application.quantitative.report_composition import (
    DESIGN_AWARE_PROMPT_VERSION,
    QuantitativeReportCompositionService,
    QuantitativeReportValidator,
)
from application.quantitative.report_lineage import (
    QuantitativeReportLineageError,
    QuantitativeReportLineageService,
)
from domain.quantitative.report_lineage import ReportCoverageStatus
from infrastructure.persistence.quantitative_insight_lineage_repository import (
    QLQuantitativeInsightLineageRepository,
)
from infrastructure.persistence.quantitative_report_lineage_repository import (
    QLQuantitativeReportLineageRepository,
)
from tests.application.quantitative.test_property_rf_insight_lineage import (
    PropertyRFInsightLineageTests as _PropertyRFInsightLineageTests,
    RecordingInsightGenerator,
)


class RecordingReportGenerator:
    identity = "rg-recording-report-v1"

    def __init__(self, *, design_fields=False, unknown=False, rejected=False, support_mode="MIXED"):
        self.calls = 0
        self.design_fields = design_fields
        self.unknown = unknown
        self.rejected = rejected
        self.support_mode = support_mode

    def generate(self, prompt):
        self.calls += 1
        support = json.loads(prompt.split("APPROVED_SUPPORT=", 1)[1])
        finding = support["findings"][0]
        insight = support["insights"][0]
        finding_id = "unknown-finding" if self.unknown else finding["finding_id"]
        narrative = finding["text"]
        values = [finding["display_value"]] if finding.get("display_value") else []
        if self.rejected:
            narrative = "The unsupported result was 999.0%."
            values = ["999.0"]
        section_finding_refs = [] if self.support_mode == "INSIGHT_ONLY" else [finding_id]
        section_insight_refs = [] if self.support_mode == "FINDING_ONLY" else [insight["insight_id"]]
        proposal = {
            "title": "Design-aware quantitative results",
            "finding_refs": [finding_id],
            "insight_refs": section_insight_refs,
            "sections": [{
                "section_id": "section-1",
                "section_type": "KEY_FINDINGS",
                "title": "Supported results",
                "narrative": narrative,
                "finding_refs": section_finding_refs,
                "insight_refs": section_insight_refs,
                "referenced_display_values": values,
                "authoritative_result_refs": list(finding["result_refs"]),
                "authoritative_table_refs": [],
                "weighting_status": finding["weighting"],
                "filter_definition": finding["filter"],
                "base_definition": finding["base"],
                "direction": finding["direction"],
            }],
        }
        if self.design_fields:
            proposal["objective_ids"] = ["fabricated-objective"]
        return proposal


class PropertyRGReportLineageTests(unittest.TestCase):
    def setUp(self):
        self.rf_fixture = _PropertyRFInsightLineageTests(methodName="runTest")
        self.rf_fixture.setUp()
        for name in (
            "project", "run", "state", "rc", "findings", "finding_record",
            "re_input", "re_manifest", "re_coverage", "rf",
        ):
            setattr(self, name, getattr(self.rf_fixture, name))
        self.rf_repository = QLQuantitativeInsightLineageRepository(self.state)
        self.rf_input = self.rf_repository.save_input_authority(
            self.rf_fixture.authority()
        )
        self.insight_generator = RecordingInsightGenerator()
        self.insight_service = QuantitativeInsightSynthesisService(
            generator=self.insight_generator,
            validator=QuantitativeInsightValidator(digest_provider=self.rc.digest),
            digest_provider=self.rc.digest,
        )
        self.insights = self.insight_service.generate(
            findings=self.findings.accepted_findings,
            post_validator=self.rf.compatibility_validator(self.rf_input),
        )
        self.insight_record = (
            f"{self.run}:insight-generation:{self.insights.generation_fingerprint}"
        )
        self.state.persist(
            self.insights,
            record_id=self.insight_record,
            project_id=self.project,
            run_id=self.run,
        )
        self.rf_manifest, self.rf_coverage = self.rf.finalize(
            authority=self.rf_input,
            generation_record_id=self.insight_record,
            generation=self.insights,
        )
        self.repository = QLQuantitativeReportLineageRepository(self.state)
        self.rg = QuantitativeReportLineageService(
            repository=self.repository,
            digest_provider=self.rc.digest,
        )

    def authority(self, **changes):
        values = dict(
            project_id=self.project,
            run_id=self.run,
            finding_generation_record_id=self.finding_record,
            findings=self.findings,
            insight_generation_record_id=self.insight_record,
            insights=self.insights,
            re_input=self.re_input,
            re_manifest=self.re_manifest,
            re_coverage=self.re_coverage,
            rf_input=self.rf_input,
            rf_manifest=self.rf_manifest,
            rf_coverage=self.rf_coverage,
        )
        values.update(changes)
        return self.rg.build_input_authority(**values)

    def report_service(self, generator):
        return QuantitativeReportCompositionService(
            generator=generator,
            validator=QuantitativeReportValidator(digest_provider=self.rc.digest),
            digest_provider=self.rc.digest,
        )

    def compose(self, authority, generator=None):
        generator = generator or RecordingReportGenerator()
        composition = self.report_service(generator).compose_design_aware(
            findings=self.findings.accepted_findings,
            insights=self.insights.accepted_insights,
            bundle=self.rg.report_bundle(authority),
            post_validator=self.rg.compatibility_validator(authority),
        )
        return generator, composition

    def test_exact_re_rf_builds_deterministic_safe_rg_input(self):
        first, second = self.authority(), self.authority()
        self.assertEqual(first, second)
        self.assertEqual(first.execution_mode, "DESIGN_AWARE_EXECUTION")
        self.assertEqual(len(first.finding_entries), len(self.findings.accepted_findings))
        self.assertEqual(len(first.insight_entries), len(self.insights.accepted_insights))
        serialized = repr(first).lower()
        for forbidden in ("respondent-0", "storage", "credential", "protected"):
            self.assertNotIn(forbidden, serialized)

    def test_stale_wrong_scope_and_missing_lineage_fail_closed(self):
        cases = (
            {"project_id": "wrong"},
            {"run_id": "wrong"},
            {"finding_generation_record_id": "wrong"},
            {"insight_generation_record_id": "wrong"},
            {"re_manifest": replace(self.re_manifest, input_authority_fingerprint="stale")},
            {"rf_manifest": replace(self.rf_manifest, input_authority_fingerprint="stale")},
            {"rf_coverage": replace(self.rf_coverage, fingerprint="stale")},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(QuantitativeReportLineageError):
                self.authority(**case)

    def test_qk_v2_is_id_only_and_application_resolves_fingerprints(self):
        authority = self.authority()
        generator, composition = self.compose(authority)
        self.assertEqual(generator.calls, 1)
        self.assertIsNotNone(composition.accepted_report)
        self.assertEqual(composition.prompt_version, DESIGN_AWARE_PROMPT_VERSION)
        self.assertEqual(
            composition.accepted_report.generation_metadata["prompt_version"],
            DESIGN_AWARE_PROMPT_VERSION,
        )
        section = composition.accepted_report.sections[0]
        self.assertEqual(
            section.finding_refs[0].validation_fingerprint,
            self.findings.accepted_findings[0].support_validation_fingerprint,
        )
        self.assertEqual(
            section.insight_refs[0].validation_fingerprint,
            self.insights.accepted_insights[0].validation_fingerprint,
        )

    def test_unknown_and_model_authored_design_references_are_rejected(self):
        authority = self.authority()
        for generator in (
            RecordingReportGenerator(unknown=True),
            RecordingReportGenerator(design_fields=True),
        ):
            with self.subTest(generator=vars(generator)):
                _, composition = self.compose(authority, generator)
                self.assertIsNone(composition.accepted_report)
                self.assertEqual(len(composition.rejected_reports), 1)

    def test_finding_only_insight_only_and_mixed_sections_are_supported(self):
        authority = self.authority()
        for mode in ("FINDING_ONLY", "INSIGHT_ONLY", "MIXED"):
            with self.subTest(mode=mode):
                _, composition = self.compose(
                    authority, RecordingReportGenerator(support_mode=mode)
                )
                self.assertIsNotNone(composition.accepted_report)

    def test_accepted_report_gets_branch_preserving_lineage_and_coverage(self):
        authority = self.repository.save_input_authority(self.authority())
        _, composition = self.compose(authority)
        record = f"{self.run}:report-composition:{composition.composition_fingerprint}"
        self.state.persist(
            composition, record_id=record, project_id=self.project, run_id=self.run
        )
        manifest, coverage = self.rg.finalize(
            authority=authority,
            report_composition_record_id=record,
            composition=composition,
        )
        replay = self.rg.finalize(
            authority=authority,
            report_composition_record_id=record,
            composition=composition,
        )
        self.assertEqual((manifest, coverage), replay)
        self.assertEqual(len(manifest.entries), 1)
        entry = manifest.entries[0]
        self.assertTrue(entry.effective_support_branches)
        self.assertTrue(
            entry.common_analytical_requirement_ids
            or entry.common_research_question_ids
        )
        self.assertIn(
            ReportCoverageStatus.REPORT_COVERED,
            {item.status for item in coverage.entries},
        )
        self.assertFalse(hasattr(entry, "objective_answered"))

    def test_rejected_report_has_truthful_coverage_and_no_lineage(self):
        authority = self.repository.save_input_authority(self.authority())
        _, composition = self.compose(
            authority, RecordingReportGenerator(rejected=True)
        )
        self.assertIsNone(composition.accepted_report)
        record = f"{self.run}:report-composition:{composition.composition_fingerprint}"
        manifest, coverage = self.rg.finalize(
            authority=authority,
            report_composition_record_id=record,
            composition=composition,
        )
        self.assertIsNone(manifest)
        self.assertIn(
            ReportCoverageStatus.REPORT_PROPOSAL_REJECTED,
            {item.status for item in coverage.entries},
        )

    def test_same_rq_is_compatible_but_common_objective_only_is_rejected(self):
        authority = self.authority()
        finding = authority.finding_entries[0]
        insight = authority.insight_entries[0]
        finding_branch = finding.branches[0]
        same_rq_branch = replace(
            finding_branch, analytical_requirement_ids=("requirement-other",)
        )
        compatible_insight = replace(
            insight,
            branches_by_finding=((finding.finding_id, (same_rq_branch,)),),
            common_analytical_requirement_ids=(),
            common_research_question_ids=same_rq_branch.research_question_ids,
        )
        compatible = replace(authority, insight_entries=(compatible_insight,))
        _, composition = self.compose(compatible)
        self.assertIsNotNone(composition.accepted_report)

        objective_only = replace(
            same_rq_branch,
            research_question_ids=("rq-other",),
            objective_ids=finding_branch.objective_ids,
        )
        incompatible_insight = replace(
            compatible_insight,
            branches_by_finding=((finding.finding_id, (objective_only,)),),
            common_research_question_ids=("rq-other",),
        )
        incompatible = replace(authority, insight_entries=(incompatible_insight,))
        _, rejected = self.compose(incompatible)
        self.assertIsNone(rejected.accepted_report)

    def test_production_vertical_restarts_without_second_qk_call(self):
        from tests.application.quantitative.test_property_re_finding_lineage import RecordingFindingGenerator

        vertical = self.rf_fixture.re_fixture._vertical(RecordingFindingGenerator())
        vertical.insights = self.insight_service
        vertical.insight_lineage = self.rf
        report_generator = RecordingReportGenerator()
        vertical.reports = self.report_service(report_generator)
        vertical.report_lineage = self.rg
        state = vertical._quant_findings(
            self.project,
            self.run,
            self.rf_fixture.re_fixture._safe_state(),
        )
        state = vertical._quant_insights(self.project, self.run, state)
        first = vertical._quant_report(self.project, self.run, state)
        second = vertical._quant_report(self.project, self.run, dict(first))
        self.assertEqual(report_generator.calls, 1)
        self.assertEqual(
            first["report_lineage_manifest_record_id"],
            second["report_lineage_manifest_record_id"],
        )
        self.assertEqual(
            first["report_coverage_manifest_record_id"],
            second["report_coverage_manifest_record_id"],
        )
    def test_reserved_input_without_generation_fails_closed_without_qk_retry(self):
        from tests.application.quantitative.test_property_re_finding_lineage import RecordingFindingGenerator

        vertical = self.rf_fixture.re_fixture._vertical(RecordingFindingGenerator())
        vertical.insights = self.insight_service
        vertical.insight_lineage = self.rf
        report_generator = RecordingReportGenerator()
        vertical.reports = self.report_service(report_generator)
        vertical.report_lineage = self.rg
        state = vertical._quant_findings(
            self.project,
            self.run,
            self.rf_fixture.re_fixture._safe_state(),
        )
        state = vertical._quant_insights(self.project, self.run, state)
        candidate = self.authority()
        self.repository.save_input_authority(candidate)
        with self.assertRaisesRegex(Exception, "retry prohibited"):
            vertical._quant_report(self.project, self.run, state)
        self.assertEqual(report_generator.calls, 0)
    def test_dataset_only_absence_is_explicit_restart_safe(self):
        authority = self.authority()
        _, composition = self.compose(authority)
        first = self.rg.dataset_only_absence(
            project_id=self.project,
            run_id=self.run,
            report_composition_record_id="dataset-only-report",
            composition=composition,
        )
        second = self.rg.dataset_only_absence(
            project_id=self.project,
            run_id=self.run,
            report_composition_record_id="dataset-only-report",
            composition=composition,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.status, "NO_DESIGN_AWARE_REPORT_LINEAGE")


if __name__ == "__main__":
    unittest.main()
