from __future__ import annotations

import io
import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from openpyxl import Workbook

from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from domain.quantitative.analysis import CrossTabAnalysisSpecification, StatisticalTable
from domain.quantitative.dataset import DatasetFormat, PiiClassification, ValidationStatus, VariableRole, VariableType
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
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


class PropertyQDCrossTabStatisticalResultProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage()
        self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest)
        self.service = CrossTabStatisticsService(storage=self.storage, digest_provider=self.digest)
        self.weight_import = WeightImportService(storage=self.storage, digest_provider=self.digest)

    def imported(self, *, rows=None, dataset_id="qd", sex_pii=False):
        rows = rows or [
            ["r1", "YES", "F", "NORTH", 1],
            ["r2", "NO", "F", "SOUTH", 3],
            ["r3", "YES", "M", "NORTH", 2],
            ["r4", "NO", "M", "SOUTH", 0],
            ["r5", None, "M", "NORTH", 4],
            ["r6", "YES", None, "SOUTH", 1],
        ]
        return self.importer.import_bytes(
            workbook_bytes(["id", "response", "sex", "region", "weight"], rows),
            filename="cross-tab.xlsx", dataset_format=DatasetFormat.XLSX,
            dataset_id=dataset_id, project_id="project-qd", run_id="run-qd", data_sheet="Data",
            overrides={
                "id": VariableOverride(role=VariableRole.TECHNICAL_ID),
                "response": VariableOverride(variable_type=VariableType.CATEGORICAL),
                "sex": VariableOverride(variable_type=VariableType.DEMOGRAPHIC, role=VariableRole.DEMOGRAPHIC, pii_classification=PiiClassification.PII_RESTRICTED if sex_pii else PiiClassification.NONE),
                "region": VariableOverride(variable_type=VariableType.DEMOGRAPHIC, role=VariableRole.DEMOGRAPHIC),
                "weight": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT),
            },
        )

    def variable(self, imported, name):
        return next(item for item in imported.codebook.variables if item.name == name)

    def quality(self, imported):
        dataset = imported.dataset_version
        fp = canonical_digest({"dataset": dataset.dataset_fingerprint, "quality": "approved"}, digest_provider=self.digest)
        return DatasetQualityAssessment(dataset.version_id, dataset.dataset_fingerprint, "qc", DatasetQualityState.QC_APPROVED, "approval", True, fp)

    def specification(self, imported, *, weighted=False, filter_region=None, row_categories=(), column_categories=()):
        row_id = self.variable(imported, "response").variable_id
        column_id = self.variable(imported, "sex").variable_id
        region_id = self.variable(imported, "region").variable_id
        filter_definition = "ALL_ROWS" if filter_region is None else self.service.filter_definition(region_id, filter_region)
        return CrossTabAnalysisSpecification(
            specification_id="response-by-sex", variable_id=row_id,
            weighting_status="WEIGHTED" if weighted else "UNWEIGHTED",
            filter_definition=filter_definition, column_variable_id=column_id,
            filter_variable_id=region_id if filter_region is not None else None,
            filter_category_value=filter_region, row_categories=tuple(row_categories),
            column_categories=tuple(column_categories),
        )

    def context(self, imported, specification, *, weights=None):
        refs = self.service.eligible_respondent_refs(dataset=imported.dataset_version, codebook=imported.codebook, specification=specification)
        if specification.weighting_status == "UNWEIGHTED":
            view = build_analytical_view(dataset=imported.dataset_version, quality=self.quality(imported), specification=specification, mode=WeightingMode.UNWEIGHTED, respondent_refs=refs, digest_provider=self.digest)
            return view, None
        weight_set = weights or self.weight_import.from_embedded_variable(dataset=imported.dataset_version, codebook=imported.codebook, variable_id=self.variable(imported, "weight").variable_id)
        approval = approve_weight_set(weight_set=weight_set, approver_id="manager", approved_at="2026-08-20T12:00:00Z", digest_provider=self.digest)
        view = build_analytical_view(dataset=imported.dataset_version, quality=self.quality(imported), specification=specification, mode=WeightingMode.WEIGHTED, respondent_refs=refs, weight_set=weight_set, approval=approval, digest_provider=self.digest)
        return view, weight_set

    def compute(self, imported, specification, *, weights=None):
        view, weight_set = self.context(imported, specification, weights=weights)
        return self.service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=specification, view=view, weight_set=weight_set)

    def test_unweighted_cross_tab_and_column_percentages(self):
        imported = self.imported()
        table, results = self.compute(imported, self.specification(imported))
        self.assertIsInstance(table, StatisticalTable)
        percentages = [item for item in results if item.statistic_type == "CROSS_TAB_COLUMN_PERCENTAGE"]
        for column in {item.column_category_value for item in percentages}:
            self.assertEqual(sum((item.value for item in percentages if item.column_category_value == column), Decimal(0)), Decimal(100))
        yes_f = next(item for item in percentages if item.row_category_value == "YES" and item.column_category_value == "F")
        self.assertEqual(yes_f.value, Decimal(50))
        self.assertEqual(yes_f.percentage_orientation, "COLUMN")

    def test_weighted_cross_tab_differs_and_preserves_unweighted_n(self):
        imported = self.imported()
        _, unweighted = self.compute(imported, self.specification(imported))
        _, weighted = self.compute(imported, self.specification(imported, weighted=True))
        unweighted_no_f = next(item for item in unweighted if item.statistic_type == "CROSS_TAB_COLUMN_PERCENTAGE" and item.row_category_value == "NO" and item.column_category_value == "F")
        weighted_no_f = next(item for item in weighted if item.statistic_type == "CROSS_TAB_COLUMN_PERCENTAGE" and item.row_category_value == "NO" and item.column_category_value == "F")
        self.assertEqual(unweighted_no_f.value, Decimal(50))
        self.assertEqual(weighted_no_f.value, Decimal(75))
        self.assertEqual(weighted_no_f.unweighted_n, 1)
        self.assertEqual(weighted_no_f.weighted_base, Decimal(3))

    def test_simple_filter_changes_results_and_provenance(self):
        imported = self.imported()
        _, all_results = self.compute(imported, self.specification(imported))
        filtered_spec = self.specification(imported, filter_region="NORTH")
        _, filtered = self.compute(imported, filtered_spec)
        self.assertNotEqual(all_results[0].reproducibility_fingerprint, filtered[0].reproducibility_fingerprint)
        self.assertEqual(next(item.value for item in filtered if item.statistic_type == "CROSS_TAB_TOTAL_VALID_BASE"), 2)

    def test_missing_dimensions_are_excluded_and_counts_remain_results(self):
        imported = self.imported()
        _, results = self.compute(imported, self.specification(imported))
        self.assertEqual(next(item.value for item in results if item.statistic_type == "CROSS_TAB_TOTAL_VALID_BASE"), 4)
        self.assertEqual(next(item.value for item in results if item.statistic_type == "CROSS_TAB_ROW_MISSING_N"), 1)
        self.assertEqual(next(item.value for item in results if item.statistic_type == "CROSS_TAB_COLUMN_MISSING_N"), 1)

    def test_changed_weight_changes_result_fingerprint_and_rerun_is_deterministic(self):
        imported = self.imported()
        spec = self.specification(imported, weighted=True)
        _, first = self.compute(imported, spec)
        _, replay = self.compute(imported, spec)
        changed = self.weight_import.from_separate_keyed_rows(dataset=imported.dataset_version, source_bytes_checksum="changed", parser_name="synthetic", parser_version="1", key_specification="technical-id", rows=(("r1", 2), ("r2", 3), ("r3", 2), ("r4", 0), ("r5", 4), ("r6", 1)))
        _, changed_results = self.compute(imported, spec, weights=changed)
        self.assertEqual(tuple(item.reproducibility_fingerprint for item in first), tuple(item.reproducibility_fingerprint for item in replay))
        self.assertNotEqual(first[0].reproducibility_fingerprint, changed_results[0].reproducibility_fingerprint)

    def test_invalid_dataset_weight_binding_fails_closed(self):
        imported = self.imported()
        other = self.imported(dataset_id="other")
        spec = self.specification(imported, weighted=True)
        view, weight_set = self.context(imported, spec)
        with self.assertRaisesRegex(ValueError, "stale|another"):
            self.service.compute(dataset=other.dataset_version, codebook=other.codebook, specification=self.specification(other, weighted=True), view=view, weight_set=weight_set)

    def test_invalid_filter_and_unknown_dimension_categories_fail_closed(self):
        imported = self.imported()
        bad_filter = replace(self.specification(imported, filter_region="NORTH"), filter_definition="ALL_ROWS")
        with self.assertRaisesRegex(ValueError, "filter"):
            self.service.eligible_respondent_refs(dataset=imported.dataset_version, codebook=imported.codebook, specification=bad_filter)
        unknown = self.specification(imported, row_categories=("UNKNOWN",))
        with self.assertRaisesRegex(ValueError, "unknown row"):
            self.compute(imported, unknown)

    def test_blocked_semantics_numeric_pii_and_technical_dimensions_fail_closed(self):
        imported = self.imported()
        spec = self.specification(imported)
        row = self.variable(imported, "response")
        blocked_row = replace(row, validation_status=ValidationStatus.BLOCKED)
        blocked_codebook = replace(imported.codebook, variables=tuple(blocked_row if item.variable_id == row.variable_id else item for item in imported.codebook.variables))
        view, _ = self.context(imported, spec)
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.service.compute(dataset=imported.dataset_version, codebook=blocked_codebook, specification=spec, view=view)
        numeric_spec = replace(spec, column_variable_id=self.variable(imported, "weight").variable_id)
        numeric_view, _ = self.context(imported, numeric_spec)
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=numeric_spec, view=numeric_view)
        pii = self.imported(dataset_id="pii", sex_pii=True)
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.compute(pii, self.specification(pii))
        technical_spec = replace(spec, column_variable_id=self.variable(imported, "id").variable_id)
        technical_view, _ = self.context(imported, technical_spec)
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=technical_spec, view=technical_view)

    def test_table_is_manifest_over_result_references_and_all_cells_are_retained(self):
        imported = self.imported()
        table, results = self.compute(imported, self.specification(imported))
        self.assertEqual(table.ordered_result_ids, tuple(item.result_id for item in results))
        self.assertFalse(any(field in table.__dataclass_fields__ for field in ("values", "cells", "percentages")))
        cell_pairs = {(item.row_category_value, item.column_category_value) for item in results if item.statistic_type == "CROSS_TAB_COLUMN_PERCENTAGE"}
        self.assertEqual(cell_pairs, {("NO", "F"), ("NO", "M"), ("YES", "F"), ("YES", "M")})

    def test_no_desk_or_external_call_dependency(self):
        import application.quantitative.cross_tab_statistics as module
        source = inspect.getsource(module)
        for forbidden in ("InformationNeed", "EvidenceExpectation", "domain.sources", "openai", "tavily", "llm_client"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
