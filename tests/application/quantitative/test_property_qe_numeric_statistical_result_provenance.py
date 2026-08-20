from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from domain.quantitative.analysis import NumericAnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, PiiClassification, ValidationStatus, VariableRole, VariableType
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qd_cross_tab_statistical_result_provenance import workbook_bytes


class PropertyQENumericStatisticalResultProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage()
        self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest)
        self.service = NumericStatisticsService(storage=self.storage, digest_provider=self.digest)
        self.weight_import = WeightImportService(storage=self.storage, digest_provider=self.digest)

    def imported(self, *, dataset_id="qe", rows=None):
        rows = rows or [[1, 10, "NORTH", 1, 100], [2, 20, "SOUTH", 3, 200], [3, 999, "NORTH", 2, 300], [4, None, "SOUTH", 0, 400]]
        return self.importer.import_bytes(
            workbook_bytes(["id", "score", "region", "weight", "income"], rows), filename="numeric.xlsx",
            dataset_format=DatasetFormat.XLSX, dataset_id=dataset_id, project_id="project-qe", run_id="run-qe", data_sheet="Data",
            overrides={
                "id": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.TECHNICAL_ID),
                "score": VariableOverride(variable_type=VariableType.NUMERIC, missing_values=(999,)),
                "region": VariableOverride(variable_type=VariableType.CATEGORICAL),
                "weight": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT),
                "income": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.PII, pii_classification=PiiClassification.PII_RESTRICTED),
            },
        )

    def variable(self, imported, name):
        return next(item for item in imported.codebook.variables if item.name == name)

    def quality(self, imported):
        dataset = imported.dataset_version
        fp = canonical_digest({"dataset": dataset.dataset_fingerprint, "quality": "approved"}, digest_provider=self.digest)
        return DatasetQualityAssessment(dataset.version_id, dataset.dataset_fingerprint, "qc", DatasetQualityState.QC_APPROVED, "approval", True, fp)

    def specification(self, imported, *, weighted=False, region=None, variable="score"):
        region_id = self.variable(imported, "region").variable_id
        definition = "ALL_ROWS" if region is None else CrossTabStatisticsService.filter_definition(region_id, region)
        return NumericAnalysisSpecification(
            specification_id=f"summary-{variable}", variable_id=self.variable(imported, variable).variable_id,
            weighting_status="WEIGHTED" if weighted else "UNWEIGHTED", filter_definition=definition,
            filter_variable_id=region_id if region is not None else None, filter_category_value=region,
        )

    def context(self, imported, specification, weight_set=None):
        refs = self.service.eligible_respondent_refs(dataset=imported.dataset_version, codebook=imported.codebook, specification=specification)
        if specification.weighting_status == "UNWEIGHTED":
            return build_analytical_view(dataset=imported.dataset_version, quality=self.quality(imported), specification=specification, mode=WeightingMode.UNWEIGHTED, respondent_refs=refs, digest_provider=self.digest), None
        weights = weight_set or self.weight_import.from_embedded_variable(dataset=imported.dataset_version, codebook=imported.codebook, variable_id=self.variable(imported, "weight").variable_id)
        approval = approve_weight_set(weight_set=weights, approver_id="manager", approved_at="2026-08-20T12:00:00Z", digest_provider=self.digest)
        view = build_analytical_view(dataset=imported.dataset_version, quality=self.quality(imported), specification=specification, mode=WeightingMode.WEIGHTED, respondent_refs=refs, weight_set=weights, approval=approval, digest_provider=self.digest)
        return view, weights

    def compute(self, imported, specification, weight_set=None):
        view, weights = self.context(imported, specification, weight_set)
        return self.service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=specification, view=view, weight_set=weights)

    def test_unweighted_contract_mean_median_min_max_valid_and_missing(self):
        imported = self.imported()
        results = self.compute(imported, self.specification(imported))
        values = {item.statistic_type: item.value for item in results}
        self.assertEqual(values["NUMERIC_VALID_N"], 2)
        self.assertEqual(values["NUMERIC_MISSING_N"], 2)
        self.assertEqual(values["NUMERIC_MEAN"], Decimal(15))
        self.assertEqual(values["NUMERIC_MEDIAN"], Decimal(15))
        self.assertEqual(values["NUMERIC_MINIMUM"], Decimal(10))
        self.assertEqual(values["NUMERIC_MAXIMUM"], Decimal(20))

    def test_filtered_numeric_summary_and_changed_filter_change_authority(self):
        imported = self.imported()
        all_results = self.compute(imported, self.specification(imported))
        north = self.compute(imported, self.specification(imported, region="NORTH"))
        self.assertEqual(next(item.value for item in north if item.statistic_type == "NUMERIC_MEAN"), Decimal(10))
        self.assertNotEqual(all_results[0].reproducibility_fingerprint, north[0].reproducibility_fingerprint)

    def test_weighted_mean_keeps_n_and_weighted_base_distinct(self):
        imported = self.imported()
        results = self.compute(imported, self.specification(imported, weighted=True))
        mean = next(item for item in results if item.statistic_type == "NUMERIC_WEIGHTED_MEAN")
        self.assertEqual(mean.value, Decimal("17.5"))
        self.assertEqual(mean.unweighted_n, 2)
        self.assertEqual(mean.weighted_base, Decimal(4))

    def test_changed_weight_changes_fingerprint_and_rerun_is_identical(self):
        imported = self.imported()
        spec = self.specification(imported, weighted=True)
        first = self.compute(imported, spec)
        replay = self.compute(imported, spec)
        changed = self.weight_import.from_separate_keyed_rows(dataset=imported.dataset_version, source_bytes_checksum="changed", parser_name="synthetic", parser_version="1", key_specification="technical-id", rows=((1, 2), (2, 3), (3, 2), (4, 0)))
        changed_results = self.compute(imported, spec, changed)
        self.assertEqual(first, replay)
        self.assertNotEqual(first[-1].reproducibility_fingerprint, changed_results[-1].reproducibility_fingerprint)

    def test_unresolved_semantics_and_non_numeric_variable_fail_closed(self):
        imported = self.imported()
        spec = self.specification(imported)
        score = self.variable(imported, "score")
        blocked = replace(score, validation_status=ValidationStatus.BLOCKED)
        codebook = replace(imported.codebook, variables=tuple(blocked if item.variable_id == score.variable_id else item for item in imported.codebook.variables))
        view, _ = self.context(imported, spec)
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.service.compute(dataset=imported.dataset_version, codebook=codebook, specification=spec, view=view)
        categorical = self.specification(imported, variable="region")
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.compute(imported, categorical)

    def test_pii_and_technical_id_fail_closed(self):
        imported = self.imported()
        for variable in ("income", "id"):
            with self.subTest(variable=variable), self.assertRaisesRegex(ValueError, "eligible"):
                self.compute(imported, self.specification(imported, variable=variable))

    def test_incompatible_weightset_and_invalid_filter_fail_closed(self):
        imported = self.imported()
        other = self.imported(dataset_id="other")
        spec = self.specification(imported, weighted=True)
        view, weights = self.context(imported, spec)
        with self.assertRaisesRegex(ValueError, "stale|another"):
            self.service.compute(dataset=other.dataset_version, codebook=other.codebook, specification=self.specification(other, weighted=True), view=view, weight_set=weights)
        bad_filter = replace(self.specification(imported, region="NORTH"), filter_definition="ALL_ROWS")
        with self.assertRaisesRegex(ValueError, "filter"):
            self.service.eligible_respondent_refs(dataset=imported.dataset_version, codebook=imported.codebook, specification=bad_filter)

    def test_invalid_runtime_numeric_value_fails_without_coercion(self):
        imported = self.imported()
        rows = list(self.storage.get_parsed_rows(imported.dataset_version.version_id))
        score_index = next(i for i, item in enumerate(imported.codebook.variables) if item.name == "score")
        broken = list(rows[0])
        broken[score_index] = "not-a-number"
        self.storage._rows[imported.dataset_version.version_id] = (tuple(broken), *rows[1:])
        with self.assertRaisesRegex(ValueError, "invalid numeric"):
            self.compute(imported, self.specification(imported))

    def test_no_desk_or_external_call_dependency(self):
        import application.quantitative.numeric_statistics as module
        source = inspect.getsource(module)
        for forbidden in ("InformationNeed", "EvidenceExpectation", "domain.sources", "openai", "tavily", "llm_client"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
