from __future__ import annotations

from dataclasses import replace
import json
import unittest

from application.quantitative.analysis_execution import QuantitativeAnalysisExecutionService
from application.quantitative.comparison_statistics import PROPORTION_METHOD
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_lineage import (
    QuantitativeFindingLineageError,
    QuantitativeFindingLineageService,
)
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.vertical_service import (
    QuantitativeVerticalPlan,
    RealQuantitativeStageService,
)
from domain.quantitative.analysis import ComparisonSpecification
from domain.quantitative.analysis_execution import AnalysisItemExecutionStatus
from domain.quantitative.analysis_plan import ComparisonResultRoleSelector, PlannedComparison
from domain.quantitative.finding_lineage import FindingCoverageStatus
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from infrastructure.persistence.quantitative_analysis_execution_repository import (
    QLQuantitativeAnalysisExecutionRepository,
)
from infrastructure.persistence.quantitative_finding_lineage_repository import (
    QLQuantitativeFindingLineageRepository,
)
from infrastructure.quantitative.storage.in_memory_dataset_storage import (
    InMemoryDatasetStorage,
)
from tests.application.quantitative import test_property_rc_analysis_plan_authority as rc


class RecordingFindingGenerator:
    identity = "re-recording-finding-v1"

    def __init__(self):
        self.calls = 0
        self.last_bundle = None

    @staticmethod
    def scalar(value):
        if not isinstance(value, dict):
            return value
        return None if value.get("type") == "missing" else value.get("value")

    def generate(self, prompt):
        self.calls += 1
        self.last_bundle = json.loads(prompt.split("AUTHORITATIVE_BUNDLE=", 1)[1])
        results = {item["result_id"]: item for item in self.last_bundle["statistical_results"]}
        comparisons = self.last_bundle["comparison_results"]
        if comparisons:
            comparison = comparisons[0]
            return {"proposals": [{
                "claim_type": "SIGNIFICANT_COMPARISON",
                "finding_text": "The authorized group comparison is statistically significant.",
                "selected_result_ids": [
                    comparison["group_a_result_id"], comparison["group_b_result_id"]
                ],
                "selected_comparison_ids": [comparison["comparison_result_id"]],
                "limitation_note": None,
            }]}
        result = next(
            item
            for item in results.values()
            if "DESCRIPTIVE_VALUE" in item["allowed_claim_types"]
        )
        return {"proposals": [{
            "claim_type": "DESCRIPTIVE_VALUE",
            "finding_text": "The authorized distribution result is supported.",
            "selected_result_ids": [result["result_id"]],
            "selected_comparison_ids": [],
            "limitation_note": None,
        }]}


class FabricatedDesignGenerator(RecordingFindingGenerator):
    def generate(self, prompt):
        result = super().generate(prompt)
        result["proposals"][0]["objective_ids"] = ["fabricated"]
        return result


class PropertyREFindingLineageTests(unittest.TestCase):
    def setUp(self):
        self.rc = rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest")
        self.rc.setUp()
        self.rc.approve()
        self.project, self.run = self.rc.project, self.rc.run
        self.dataset, self.codebook = self.rc.dataset, self.rc.codebook
        self.quality = DatasetQualityAssessment(
            self.dataset.version_id,
            self.dataset.dataset_fingerprint,
            "qc-run",
            DatasetQualityState.QC_APPROVED,
            "qc-approval-fingerprint",
            True,
            "quality-fp",
        )
        self.projection = self.rc.service.execution_projection(
            project_id=self.project,
            run_id=self.run,
            dataset=self.dataset,
            codebook=self.codebook,
            quality_assessment=self.quality,
        )
        self.storage = InMemoryDatasetStorage()
        values = tuple(
            tuple(item[0] for item in variable.value_labels) or (1, 2)
            for variable in self.codebook.variables
        )
        rows = tuple(
            tuple(options[index % len(options)] for options in values)
            for index in range(24)
        )
        self.storage.put_parsed_rows(self.dataset.version_id, rows)
        self.storage.put_respondent_lineage(
            self.dataset.version_id, tuple(f"respondent-{index}" for index in range(24))
        )
        self.state = QuantitativeStateService(
            repository=self.rc.backing, digest_provider=self.rc.digest
        )
        self.execution_repository = QLQuantitativeAnalysisExecutionRepository(self.state)
        self.execution = QuantitativeAnalysisExecutionService(
            repository=self.execution_repository,
            state_service=self.state,
            storage=self.storage,
            digest_provider=self.rc.digest,
        )
        self.manifest = self.execution.execute(
            project_id=self.project,
            run_id=self.run,
            projection=self.projection,
            dataset=self.dataset,
            codebook=self.codebook,
            quality=self.quality,
            qc_approval_id="qc-approval",
            qc_approval_fingerprint=self.quality.approval_fingerprint,
        )
        self.repository = QLQuantitativeFindingLineageRepository(self.state)
        self.lineage = QuantitativeFindingLineageService(
            repository=self.repository,
            analysis_execution_repository=self.execution_repository,
            state_service=self.state,
            digest_provider=self.rc.digest,
        )

    def authority(self, **changes):
        values = dict(
            project_id=self.project,
            run_id=self.run,
            manifest=self.manifest,
            projection=self.projection,
            dataset=self.dataset,
            codebook=self.codebook,
        )
        values.update(changes)
        return self.lineage.build_input_authority(**values)

    def finding_service(self, generator):
        return QuantitativeFindingGenerationService(
            generator=generator,
            support_validator=QuantitativeFindingSupportValidator(
                digest_provider=self.rc.digest
            ),
            digest_provider=self.rc.digest,
        )

    def test_current_rd_builds_deterministic_safe_authority_and_multiple_results_share_owner(self):
        first = self.authority()
        second = self.authority()
        self.assertEqual(first, second)
        self.assertGreater(len(first.analysis_entries), 1)
        self.assertEqual(
            {item.planned_analysis_id for item in first.analysis_entries},
            {"analysis-brand"},
        )
        self.assertNotIn("respondent-0", repr(first))
        self.assertTrue(
            all(item.obligation == "MANDATORY" for item in first.analysis_entries)
        )

    def test_stale_authority_matrix_fails_closed(self):
        cases = (
            {"project_id": "wrong-project"},
            {"run_id": "wrong-run"},
            {"dataset": replace(self.dataset, dataset_fingerprint="changed")},
            {"codebook": replace(self.codebook, fingerprint="changed")},
            {"manifest": replace(self.manifest, plan_fingerprint="changed")},
            {"manifest": replace(self.manifest, quality_assessment_fingerprint="changed")},
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(QuantitativeFindingLineageError):
                    self.authority(**case)

    def test_duplicate_result_ownership_fails_before_generator(self):
        original = self.execution_repository.get_analysis_outcome(
            self.manifest.analysis_outcome_ids[0], project_id=self.project
        )
        duplicate = replace(
            original,
            outcome_id="duplicate-outcome",
            execution_identity="duplicate-execution",
            fingerprint="duplicate-outcome-fingerprint",
        )
        self.execution_repository.save_analysis_outcome(duplicate)
        manifest = replace(
            self.manifest,
            analysis_outcome_ids=self.manifest.analysis_outcome_ids + (duplicate.outcome_id,),
        )
        generator = RecordingFindingGenerator()
        with self.assertRaisesRegex(QuantitativeFindingLineageError, "ambiguous"):
            self.authority(manifest=manifest)
        self.assertEqual(generator.calls, 0)

    def test_accepted_finding_gets_lineage_and_rejected_design_ids_do_not(self):
        authority = self.repository.save_input_authority(self.authority())
        results, comparisons = self.lineage.load_results(authority)
        generator = RecordingFindingGenerator()
        generated = self.finding_service(generator).generate(
            statistical_results=results,
            comparison_results=comparisons,
            limitations=self.lineage.generation_limitations(authority),
        )
        record_id = f"{self.run}:finding-generation:{generated.generation_fingerprint}"
        self.state.persist(
            generated,
            record_id=record_id,
            project_id=self.project,
            run_id=self.run,
        )
        manifest, coverage = self.lineage.finalize(
            authority=authority,
            generation_record_id=record_id,
            generation=generated,
        )
        self.assertEqual(len(manifest.entries), 1)
        self.assertEqual(manifest.entries[0].objective_ids, ("objective-brand",))
        self.assertEqual(
            coverage.entries[0].status, FindingCoverageStatus.FINDING_SUPPORTED
        )
        fabricated = self.finding_service(FabricatedDesignGenerator()).generate(
            statistical_results=results,
            limitations=self.lineage.generation_limitations(authority),
        )
        self.assertEqual(fabricated.accepted_findings, ())
        self.assertEqual(len(fabricated.rejected_findings), 1)

    def test_optional_failure_does_not_block_but_mandatory_incompletion_does(self):
        item = self.projection.planned_analyses[0]
        optional_projection = replace(
            self.projection,
            planned_analyses=(replace(item, obligation="OPTIONAL"),),
        )
        optional = self.authority(projection=optional_projection)
        self.assertTrue(optional.analysis_entries)
        failed = self.execution_repository.get_analysis_outcome(
            self.manifest.analysis_outcome_ids[0], project_id=self.project
        )
        failed = replace(
            failed,
            status=AnalysisItemExecutionStatus.FAILED_EXECUTION,
            artifacts=(),
            failure_category="TEST",
        )
        self.execution_repository.save_analysis_outcome(
            replace(failed, outcome_id="failed-mandatory", fingerprint="failed-fp")
        )
        blocked_manifest = replace(
            self.manifest, analysis_outcome_ids=("failed-mandatory",)
        )
        with self.assertRaisesRegex(QuantitativeFindingLineageError, "mandatory"):
            self.authority(manifest=blocked_manifest)

    def test_restart_reuses_completed_vertical_authority_without_second_generation(self):
        generator = RecordingFindingGenerator()
        service = self._vertical(generator)
        state = self._safe_state()
        first = service._quant_findings(self.project, self.run, state)
        second = service._quant_findings(self.project, self.run, dict(first))
        self.assertEqual(generator.calls, 1)
        self.assertEqual(
            first["finding_lineage_manifest_record_id"],
            second["finding_lineage_manifest_record_id"],
        )

    def test_reserved_input_without_generation_fails_closed_without_retry(self):
        authority = self.repository.save_input_authority(self.authority())
        generator = RecordingFindingGenerator()
        with self.assertRaisesRegex(Exception, "semantic retry forbidden"):
            self._vertical(generator)._quant_findings(
                self.project, self.run, self._safe_state()
            )
        self.assertEqual(generator.calls, 0)
        self.assertIsNotNone(
            self.repository.get_input_authority(
                authority.authority_id, project_id=self.project
            )
        )

    def test_successful_comparison_reaches_production_vertical_and_lineage(self):
        other = rc.PropertyRCAnalysisPlanAuthorityTests(methodName="runTest")
        other.setUp()
        row = other.binding.actual_variable_id
        column = other.sex_binding.actual_variable_id
        row_values = tuple(item[0] for item in other.codebook.variable_by_id(row).value_labels)
        column_values = tuple(item[0] for item in other.codebook.variable_by_id(column).value_labels)
        spec = ComparisonSpecification(
            "re-comparison", PROPORTION_METHOD, row, column,
            column_values[0], column_values[1], row_values[0],
        )
        payload = {
            "id": spec.comparison_id,
            "method": spec.method,
            "variable": spec.variable_id,
            "group": spec.group_variable_id,
            "a": canonical_scalar(spec.group_a_category),
            "b": canonical_scalar(spec.group_b_category),
            "outcome": canonical_scalar(spec.outcome_category),
            "alpha": canonical_scalar(spec.alpha),
            "sidedness": spec.sidedness,
            "minimum": spec.minimum_group_base,
            "filter": spec.filter_definition,
            "base": spec.base_definition,
            "version": spec.method_version,
        }
        fingerprint = canonical_digest(payload, digest_provider=other.digest)
        spec = replace(spec, fingerprint=fingerprint)
        selectors = (
            ComparisonResultRoleSelector(
                "GROUP_A", "analysis-brand", "CROSS_TAB_COLUMN_PERCENTAGE",
                row, column, row_values[0], column_values[0], "ALL_ROWS",
            ),
            ComparisonResultRoleSelector(
                "GROUP_B", "analysis-brand", "CROSS_TAB_COLUMN_PERCENTAGE",
                row, column, row_values[0], column_values[1], "ALL_ROWS",
            ),
        )
        comparison = PlannedComparison(
            "planned-re-comparison", spec, fingerprint, ("analysis-brand",),
            ("question-preference",), ("requirement-preference",),
            "SIGNIFICANCE", result_role_selectors=selectors,
            objective_ids=("objective-brand",),
        )
        draft = other.create(planned_comparisons=(comparison,))
        other.approve(draft)
        quality = DatasetQualityAssessment(
            other.dataset.version_id, other.dataset.dataset_fingerprint, "qc",
            DatasetQualityState.QC_APPROVED, "qc-fp", True, "re-quality-fp",
        )
        projection = other.service.execution_projection(
            project_id=other.project, run_id=other.run, dataset=other.dataset,
            codebook=other.codebook, quality_assessment=quality,
        )
        storage = InMemoryDatasetStorage()
        options = tuple(
            tuple(item[0] for item in variable.value_labels) or (1, 2)
            for variable in other.codebook.variables
        )
        rows = tuple(
            tuple(values[index % len(values)] for values in options)
            for index in range(80)
        )
        storage.put_parsed_rows(other.dataset.version_id, rows)
        storage.put_respondent_lineage(
            other.dataset.version_id, tuple(f"comparison-{index}" for index in range(80))
        )
        state = QuantitativeStateService(repository=other.backing, digest_provider=other.digest)
        execution_repository = QLQuantitativeAnalysisExecutionRepository(state)
        execution = QuantitativeAnalysisExecutionService(
            repository=execution_repository, state_service=state,
            storage=storage, digest_provider=other.digest,
        )
        rd_manifest = execution.execute(
            project_id=other.project, run_id=other.run, projection=projection,
            dataset=other.dataset, codebook=other.codebook, quality=quality,
            qc_approval_id="qc", qc_approval_fingerprint="qc-fp",
        )
        re_repository = QLQuantitativeFindingLineageRepository(state)
        lineage = QuantitativeFindingLineageService(
            repository=re_repository,
            analysis_execution_repository=execution_repository,
            state_service=state,
            digest_provider=other.digest,
        )
        generator = RecordingFindingGenerator()
        vertical = RealQuantitativeStageService(
            plan=QuantitativeVerticalPlan(
                b"", "existing.sav", other.dataset.dataset_id, {}, None, (), "",
                None, None, None, None,
            ),
            storage=storage, digest_provider=other.digest, state_service=state,
            approval_service=object(),
            finding_service=QuantitativeFindingGenerationService(
                generator=generator,
                support_validator=QuantitativeFindingSupportValidator(digest_provider=other.digest),
                digest_provider=other.digest,
            ),
            insight_service=object(), report_service=object(), importers=(),
            analysis_execution_service=execution,
            analysis_execution_projection=projection,
            finding_lineage_service=lineage,
        )
        state.persist(
            other.dataset, record_id="re-comparison-dataset", project_id=other.project,
            run_id=other.run, dataset_version_id=other.dataset.version_id,
        )
        state.persist(
            other.codebook, record_id="re-comparison-codebook", project_id=other.project,
            run_id=other.run, dataset_version_id=other.dataset.version_id,
        )
        safe = {
            "analysis_execution_mode": "DESIGN_AWARE_EXECUTION",
            "analysis_execution_manifest_record_id": rd_manifest.manifest_id,
            "dataset_record_id": "re-comparison-dataset",
            "codebook_record_id": "re-comparison-codebook",
        }
        updated = vertical._quant_findings(other.project, other.run, safe)
        generated = state.load(
            updated["finding_generation_record_id"], project_id=other.project,
            expected_type=__import__("domain.quantitative.finding", fromlist=["QuantitativeFindingGenerationResult"]).QuantitativeFindingGenerationResult,
        )
        lineage_manifest = re_repository.get_manifest(
            updated["finding_lineage_manifest_record_id"], project_id=other.project
        )
        self.assertEqual(generator.calls, 1)
        self.assertEqual(len(generator.last_bundle["comparison_results"]), 1)
        self.assertEqual(len(generated.accepted_findings), 1)
        self.assertEqual(
            lineage_manifest.entries[0].planned_comparison_ids,
            ("planned-re-comparison",),
        )
    def test_dataset_only_absence_is_explicit_and_restart_safe(self):
        generator = RecordingFindingGenerator()
        results, _ = self.lineage.load_results(self.authority())
        generated = self.finding_service(generator).generate(statistical_results=results)
        absence = self.lineage.dataset_only_absence(
            project_id=self.project,
            run_id=self.run,
            generation_record_id="dataset-only-generation",
            generation=generated,
        )
        replay = self.lineage.dataset_only_absence(
            project_id=self.project,
            run_id=self.run,
            generation_record_id="dataset-only-generation",
            generation=generated,
        )
        self.assertEqual(absence, replay)
        self.assertEqual(absence.status, "NO_DESIGN_AWARE_FINDING_LINEAGE")
        self.assertFalse(hasattr(absence, "objective_ids"))

    def _vertical(self, generator):
        return RealQuantitativeStageService(
            plan=QuantitativeVerticalPlan(
                b"", "existing.sav", self.dataset.dataset_id, {}, None, (), "",
                None, None, None, None,
            ),
            storage=self.storage,
            digest_provider=self.rc.digest,
            state_service=self.state,
            approval_service=object(),
            finding_service=self.finding_service(generator),
            insight_service=object(),
            report_service=object(),
            importers=(),
            generation_mode="offline",
            analysis_execution_service=self.execution,
            analysis_execution_projection=self.projection,
            finding_lineage_service=self.lineage,
        )

    def _safe_state(self):
        dataset_record = "re-dataset-record"
        codebook_record = "re-codebook-record"
        for value, record_id in (
            (self.dataset, dataset_record),
            (self.codebook, codebook_record),
        ):
            try:
                self.state.persist(
                    value,
                    record_id=record_id,
                    project_id=self.project,
                    run_id=self.run,
                    dataset_version_id=self.dataset.version_id,
                )
            except ValueError:
                pass
        return {
            "analysis_execution_mode": "DESIGN_AWARE_EXECUTION",
            "analysis_execution_manifest_record_id": self.manifest.manifest_id,
            "dataset_record_id": dataset_record,
            "codebook_record_id": codebook_record,
        }


if __name__ == "__main__":
    unittest.main()
