from __future__ import annotations

import io
import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from openpyxl import Workbook

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.quality_control import CleaningEngine, build_cleaning_decision, build_cleaning_decision_set
from application.quantitative.weighted_one_way_statistics import WeightedOneWayStatisticsService
from application.quantitative.weighting import WeightImportService, WeightingError, approve_weight_set, build_analytical_view
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, VariableRole, VariableType
from domain.quantitative.quality import ApprovalState, CleaningAction, DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightValidationStatus, WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


def workbook_bytes(headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class PropertyQCImportedWeightSetAnalyticalViewTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage()
        self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest
        )
        self.weights = WeightImportService(storage=self.storage, digest_provider=self.digest)
        self.statistics = WeightedOneWayStatisticsService(storage=self.storage, digest_provider=self.digest)

    def imported(self, rows=None, dataset_id="qc"):
        rows = rows or [["r1", "A", 10, 1], ["r2", "A", 20, 0], ["r3", "B", 30, 3]]
        return self.importer.import_bytes(
            workbook_bytes(["id", "segment", "score", "weight"], rows),
            filename="synthetic.xlsx",
            dataset_format=DatasetFormat.XLSX,
            dataset_id=dataset_id,
            project_id="project-qc",
            run_id="run-qc",
            data_sheet="Data",
            overrides={
                "id": VariableOverride(role=VariableRole.TECHNICAL_ID),
                "segment": VariableOverride(variable_type=VariableType.CATEGORICAL),
                "score": VariableOverride(variable_type=VariableType.NUMERIC),
                "weight": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT),
            },
        )

    def quality(self, imported):
        dataset = imported.dataset_version
        fingerprint = canonical_digest({"dataset": dataset.dataset_fingerprint, "state": "QC_APPROVED"}, digest_provider=self.digest)
        return DatasetQualityAssessment(dataset.version_id, dataset.dataset_fingerprint, "qc-run", DatasetQualityState.QC_APPROVED, "manager", True, fingerprint)

    def variable(self, imported, name):
        return next(item for item in imported.codebook.variables if item.name == name)

    def specification(self, imported, name):
        return AnalysisSpecification("weighted-one-way", self.variable(imported, name).variable_id, weighting_status="WEIGHTED")

    def approved_view(self, imported, weight_set, name="segment"):
        approval = approve_weight_set(weight_set=weight_set, approver_id="manager", approved_at="2026-08-20T12:00:00Z", digest_provider=self.digest)
        view = build_analytical_view(
            dataset=imported.dataset_version,
            quality=self.quality(imported),
            specification=self.specification(imported, name),
            mode=WeightingMode.WEIGHTED,
            respondent_refs=imported.analytical_respondent_ids,
            weight_set=weight_set,
            approval=approval,
            digest_provider=self.digest,
        )
        return approval, view

    def embedded(self, imported):
        return self.weights.from_embedded_variable(
            dataset=imported.dataset_version,
            codebook=imported.codebook,
            variable_id=self.variable(imported, "weight").variable_id,
        )

    def separate(self, imported, rows):
        return self.weights.from_separate_keyed_rows(
            dataset=imported.dataset_version,
            source_bytes_checksum="separate-weight-file-sha256",
            parser_name="synthetic",
            parser_version="1",
            key_specification="technical-id",
            rows=tuple(rows),
        )

    def test_embedded_import_zero_weight_is_valid_warning_and_weight_is_not_dimension(self):
        imported = self.imported()
        weight_set = self.embedded(imported)
        replay = self.embedded(imported)
        self.assertEqual(weight_set, replay)
        self.assertEqual(weight_set.validation_status, WeightValidationStatus.VALID_WITH_WARNINGS)
        self.assertEqual(weight_set.zero_weight_count, 1)
        self.assertEqual(weight_set.sum_weights, Decimal("4"))
        self.assertFalse(self.variable(imported, "weight").analytically_eligible)
        self.assertEqual(weight_set.source_checksum, imported.dataset_version.file_checksum)
        self.assertEqual(weight_set.source_variable_fingerprint, self.variable(imported, "weight").fingerprint)

    def test_separate_keyed_import_rebinds_reordered_raw_ids_without_exposing_them(self):
        imported = self.imported()
        first = self.separate(imported, (("r3", 3), ("r1", 1), ("r2", 0)))
        second = self.separate(imported, (("r1", 1), ("r2", 0), ("r3", 3)))
        self.assertEqual(first.vector_fingerprint, second.vector_fingerprint)
        self.assertEqual(first.weight_vector, second.weight_vector)
        self.assertFalse(any("r1" in ref or "r2" in ref or "r3" in ref for ref, _ in first.weight_vector))

    def test_separate_import_requires_binding_and_source_provenance_changes_authority(self):
        data = workbook_bytes(["segment", "score", "weight"], [["A", 1, 1]])
        unbound = self.importer.import_bytes(data, filename="unbound.xlsx", dataset_format=DatasetFormat.XLSX, dataset_id="unbound", project_id="project", run_id="run", data_sheet="Data")
        with self.assertRaisesRegex(WeightingError, "binding"):
            self.separate(unbound, (("r1", 1),))
        imported = self.imported()
        one = self.separate(imported, (("r1", 1), ("r2", 2), ("r3", 3)))
        two = self.weights.from_separate_keyed_rows(dataset=imported.dataset_version, source_bytes_checksum="changed-checksum", parser_name="synthetic", parser_version="1", key_specification="technical-id", rows=(("r1", 1), ("r2", 2), ("r3", 3)))
        self.assertNotEqual(one.reproducibility_fingerprint, two.reproducibility_fingerprint)
        self.assertEqual(one.maximum_weight, Decimal("3"))

    def test_validation_blocks_missing_duplicate_unknown_negative_and_nonfinite(self):
        imported = self.imported()
        cases = (
            (("r1", 1), ("r2", 2)),
            (("r1", 1), ("r1", 2), ("r2", 2), ("r3", 3)),
            (("r1", 1), ("r2", 2), ("r3", 3), ("unknown", 4)),
            (("r1", -1), ("r2", 2), ("r3", 3)),
            (("r1", "NaN"), ("r2", 2), ("r3", 3)),
        )
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(self.separate(imported, rows).validation_status, WeightValidationStatus.BLOCKED)

    def test_changed_weight_or_dataset_breaks_authority(self):
        imported = self.imported()
        one = self.separate(imported, (("r1", 1), ("r2", 2), ("r3", 3)))
        two = self.separate(imported, (("r1", 1), ("r2", 2), ("r3", 4)))
        self.assertNotEqual(one.vector_fingerprint, two.vector_fingerprint)
        approval, _ = self.approved_view(imported, one)
        other = self.imported(dataset_id="other")
        with self.assertRaisesRegex(WeightingError, "current"):
            build_analytical_view(dataset=other.dataset_version, quality=self.quality(other), specification=self.specification(other, "segment"), mode=WeightingMode.WEIGHTED, respondent_refs=other.analytical_respondent_ids, weight_set=one, approval=approval, digest_provider=self.digest)

    def test_cleaning_preserves_protected_binding_and_classifies_excluded_parent_weight(self):
        imported = self.imported()
        excluded_ref = imported.analytical_respondent_ids[1]
        decision = build_cleaning_decision(parent=imported.dataset_version, action=CleaningAction.EXCLUDE_RESPONDENTS, affected_refs=(excluded_ref,), variable_ids=(), transformation=(), rationale="approved exclusion", actor_id="manager", digest_provider=self.digest)
        decisions = build_cleaning_decision_set(parent=imported.dataset_version, decisions=(decision,), approval_state=ApprovalState.APPROVED, approver_id="manager", approved_at="2026-08-20T12:00:00Z", digest_provider=self.digest)
        child = CleaningEngine(storage=self.storage, digest_provider=self.digest).execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=decisions)
        weights = self.weights.from_separate_keyed_rows(dataset=child, source_bytes_checksum="weights", parser_name="synthetic", parser_version="1", key_specification="technical-id", rows=(("r1", 1), ("r2", 9), ("r3", 3)))
        self.assertEqual(weights.excluded_parent_row_count, 1)
        self.assertEqual(weights.validation_status, WeightValidationStatus.VALID_WITH_WARNINGS)
        self.assertEqual(weights.sum_weights, Decimal("4"))

    def test_weighted_categorical_keeps_unweighted_n_and_weighted_base_distinct(self):
        imported = self.imported()
        weight_set = self.embedded(imported)
        _, view = self.approved_view(imported, weight_set)
        results = self.statistics.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.specification(imported, "segment"), view=view, weight_set=weight_set)
        by_type = {}
        for result in results:
            by_type.setdefault(result.statistic_type, []).append(result)
            self.assertEqual(result.weight_set_fingerprint, weight_set.reproducibility_fingerprint)
            self.assertEqual(result.analytical_view_fingerprint, view.fingerprint)
        self.assertEqual(by_type["UNWEIGHTED_VALID_N"][0].value, 3)
        self.assertEqual(by_type["WEIGHTED_VALID_BASE"][0].value, Decimal("4"))
        category_a = next(item for item in by_type["WEIGHTED_PERCENTAGE"] if item.category_value == "A")
        self.assertEqual(category_a.unweighted_n, 2)
        self.assertEqual(category_a.weighted_base, Decimal("1"))
        self.assertEqual(category_a.value, Decimal("25"))

    def test_weighted_numeric_mean_is_exact_and_no_weighted_median_is_emitted(self):
        imported = self.imported()
        weight_set = self.embedded(imported)
        _, view = self.approved_view(imported, weight_set, "score")
        results = self.statistics.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.specification(imported, "score"), view=view, weight_set=weight_set)
        types = {item.statistic_type for item in results}
        self.assertEqual(next(item.value for item in results if item.statistic_type == "WEIGHTED_MEAN"), Decimal("25"))
        self.assertNotIn("WEIGHTED_MEDIAN", types)

    def test_one_percent_category_is_computed_but_default_hidden_without_rounding_identity(self):
        rows = [[f"r{i}", "RARE" if i == 0 else "COMMON", i, 1] for i in range(100)]
        imported = self.imported(rows=rows, dataset_id="threshold")
        weight_set = self.embedded(imported)
        _, view = self.approved_view(imported, weight_set)
        results = self.statistics.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.specification(imported, "segment"), view=view, weight_set=weight_set)
        rare = next(item for item in results if item.statistic_type == "WEIGHTED_PERCENTAGE" and item.category_value == "RARE")
        self.assertEqual(rare.value, Decimal("1"))
        self.assertFalse(rare.presentation_eligible)
        replay = self.statistics.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.specification(imported, "segment"), view=view, weight_set=weight_set)
        self.assertEqual(tuple(item.reproducibility_fingerprint for item in results), tuple(item.reproducibility_fingerprint for item in replay))

    def test_all_zero_weight_valid_base_fails_closed(self):
        imported = self.imported(rows=[["r1", "A", 10, 0], ["r2", "B", 20, 0]])
        weight_set = self.embedded(imported)
        _, view = self.approved_view(imported, weight_set)
        with self.assertRaisesRegex(ValueError, "positive"):
            self.statistics.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.specification(imported, "segment"), view=view, weight_set=weight_set)

    def test_blocked_weightset_cannot_be_approved_and_unweighted_view_cannot_bind_it(self):
        imported = self.imported()
        blocked = self.separate(imported, (("r1", 1),))
        with self.assertRaisesRegex(WeightingError, "blocked"):
            approve_weight_set(weight_set=blocked, approver_id="manager", approved_at="now", digest_provider=self.digest)
        valid = self.embedded(imported)
        approval = approve_weight_set(weight_set=valid, approver_id="manager", approved_at="now", digest_provider=self.digest)
        with self.assertRaisesRegex(WeightingError, "unweighted"):
            build_analytical_view(dataset=imported.dataset_version, quality=self.quality(imported), specification=self.specification(imported, "segment"), mode=WeightingMode.UNWEIGHTED, respondent_refs=imported.analytical_respondent_ids, weight_set=valid, approval=approval, digest_provider=self.digest)

    def test_no_desk_research_or_external_client_dependency(self):
        import application.quantitative.weighting as weighting_module
        import application.quantitative.weighted_one_way_statistics as statistics_module
        source = inspect.getsource(weighting_module) + inspect.getsource(statistics_module)
        for forbidden in ("InformationNeed", "EvidenceExpectation", "domain.sources", "openai", "tavily", "llm_client"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
