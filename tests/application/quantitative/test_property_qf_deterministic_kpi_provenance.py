from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.kpi_statistics import KpiStatisticsService
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from domain.quantitative.analysis import CustomIndexAnalysisSpecification, IndexTerm, NpsAnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, PiiClassification, VariableRole, VariableType
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qd_cross_tab_statistical_result_provenance import workbook_bytes


class PropertyQFDeterministicKpiProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage(); self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest)
        self.service = KpiStatisticsService(storage=self.storage, digest_provider=self.digest)
        self.weight_import = WeightImportService(storage=self.storage, digest_provider=self.digest)
        self.imported = self.importer.import_bytes(
            workbook_bytes(["id", "nps", "region", "weight", "x", "y", "secret"], [
                [1, 0, "N", 1, 2, 10, 100], [2, 6, "S", 1, 4, 20, 200], [3, 7, "N", 1, 6, 30, 300],
                [4, 8, "S", 1, 8, 40, 400], [5, 9, "N", 3, 10, 50, 500], [6, 10, "S", 3, 12, 60, 600],
            ]), filename="kpi.xlsx", dataset_format=DatasetFormat.XLSX, dataset_id="qf", project_id="p", run_id="r", data_sheet="Data",
            overrides={"id": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.TECHNICAL_ID), "nps": VariableOverride(variable_type=VariableType.NUMERIC), "region": VariableOverride(variable_type=VariableType.CATEGORICAL), "weight": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT), "x": VariableOverride(variable_type=VariableType.NUMERIC), "y": VariableOverride(variable_type=VariableType.NUMERIC), "secret": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.PII, pii_classification=PiiClassification.PII_RESTRICTED)},
        )

    def variable(self, name): return next(item for item in self.imported.codebook.variables if item.name == name)
    def quality(self):
        d = self.imported.dataset_version; fp = canonical_digest({"dataset": d.dataset_fingerprint, "q": "approved"}, digest_provider=self.digest)
        return DatasetQualityAssessment(d.version_id, d.dataset_fingerprint, "qc", DatasetQualityState.QC_APPROVED, "approval", True, fp)
    def nps_spec(self, *, weighted=False, region=None):
        region_id = self.variable("region").variable_id
        return NpsAnalysisSpecification("nps", self.variable("nps").variable_id, weighting_status="WEIGHTED" if weighted else "UNWEIGHTED", filter_definition="ALL_ROWS" if region is None else CrossTabStatisticsService.filter_definition(region_id, region), filter_variable_id=region_id if region else None, filter_category_value=region)
    def index_spec(self, *, weighted=False):
        terms = (IndexTerm(self.variable("x").variable_id, Decimal("0.5")), IndexTerm(self.variable("y").variable_id, Decimal("2")))
        return CustomIndexAnalysisSpecification("index", self.variable("x").variable_id, weighting_status="WEIGHTED" if weighted else "UNWEIGHTED", terms=terms, intercept=Decimal(1))
    def context(self, spec, weight_set=None):
        d = self.imported.dataset_version; refs = self.service.eligible_respondent_refs(dataset=d, codebook=self.imported.codebook, specification=spec)
        if spec.weighting_status == "UNWEIGHTED": return build_analytical_view(dataset=d, quality=self.quality(), specification=spec, mode=WeightingMode.UNWEIGHTED, respondent_refs=refs, digest_provider=self.digest), None
        weights = weight_set or self.weight_import.from_embedded_variable(dataset=d, codebook=self.imported.codebook, variable_id=self.variable("weight").variable_id)
        approval = approve_weight_set(weight_set=weights, approver_id="m", approved_at="now", digest_provider=self.digest)
        return build_analytical_view(dataset=d, quality=self.quality(), specification=spec, mode=WeightingMode.WEIGHTED, respondent_refs=refs, digest_provider=self.digest, weight_set=weights, approval=approval), weights
    def nps(self, spec, weights=None):
        view, weight_set = self.context(spec, weights); return self.service.compute_nps(dataset=self.imported.dataset_version, codebook=self.imported.codebook, specification=spec, view=view, weight_set=weight_set)
    def index(self, spec):
        view, weights = self.context(spec); return self.service.compute_custom_index(dataset=self.imported.dataset_version, codebook=self.imported.codebook, specification=spec, view=view, weight_set=weights)

    def test_standard_unweighted_nps_components_and_final(self):
        results = self.nps(self.nps_spec()); values = {item.statistic_type: item.value for item in results}
        self.assertEqual(values["NPS_DETRACTOR_SHARE"], Decimal(100) / Decimal(3)); self.assertEqual(values["NPS_PROMOTER_SHARE"], Decimal(100) / Decimal(3)); self.assertEqual(values["NPS"], Decimal(0))
        self.assertTrue(all(item.computation_version == "qf-1" for item in results))

    def test_weighted_nps_preserves_n_and_base(self):
        final = next(item for item in self.nps(self.nps_spec(weighted=True)) if item.statistic_type == "NPS")
        self.assertEqual(final.value, Decimal(40)); self.assertEqual(final.unweighted_n, 6); self.assertEqual(final.weighted_base, Decimal(10))

    def test_filtered_nps_and_deterministic_rerun(self):
        spec = self.nps_spec(region="N"); first = self.nps(spec); second = self.nps(spec)
        self.assertEqual(first, second); self.assertEqual(next(item.value for item in first if item.statistic_type == "NPS"), Decimal(0))

    def test_changed_weight_and_specification_change_fingerprint(self):
        spec = self.nps_spec(weighted=True); original = self.nps(spec)
        changed = self.weight_import.from_separate_keyed_rows(dataset=self.imported.dataset_version, source_bytes_checksum="changed", parser_name="s", parser_version="1", key_specification="id", rows=((1, 1), (2, 1), (3, 1), (4, 1), (5, 4), (6, 4)))
        changed_results = self.nps(spec, changed)
        changed_spec = replace(self.nps_spec(), passive_range=(7, 7), promoter_range=(8, 10))
        self.assertNotEqual(original[-2].reproducibility_fingerprint, changed_results[-2].reproducibility_fingerprint)
        self.assertNotEqual(self.nps(self.nps_spec())[-2].reproducibility_fingerprint, self.nps(changed_spec)[-2].reproducibility_fingerprint)

    def test_simple_custom_index_is_exact_and_versioned(self):
        result = next(item for item in self.index(self.index_spec()) if item.statistic_type == "CUSTOM_INDEX")
        self.assertEqual(result.value, Decimal("74.5")); self.assertEqual(result.unweighted_n, 6); self.assertEqual(result.computation_method, "deterministic_custom_index")

    def test_invalid_nps_and_index_specs_fail_closed(self):
        bad_nps = replace(self.nps_spec(), passive_range=(6, 8))
        view, _ = self.context(bad_nps)
        with self.assertRaisesRegex(ValueError, "ranges"):
            self.service.compute_nps(dataset=self.imported.dataset_version, codebook=self.imported.codebook, specification=bad_nps, view=view)
        bad_index = replace(self.index_spec(), terms=())
        view, _ = self.context(bad_index)
        with self.assertRaisesRegex(ValueError, "index"):
            self.service.compute_custom_index(dataset=self.imported.dataset_version, codebook=self.imported.codebook, specification=bad_index, view=view)

    def test_pii_technical_and_incompatible_weight_fail_closed(self):
        for source in ("secret", "id"):
            spec = replace(self.nps_spec(), variable_id=self.variable(source).variable_id); view, _ = self.context(spec)
            with self.assertRaisesRegex(ValueError, "eligible"):
                self.service.compute_nps(dataset=self.imported.dataset_version, codebook=self.imported.codebook, specification=spec, view=view)
        other = replace(self.imported.dataset_version, version_id="other", dataset_fingerprint="other")
        spec = self.nps_spec(weighted=True); view, weights = self.context(spec)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.service.compute_nps(dataset=other, codebook=self.imported.codebook, specification=spec, view=view, weight_set=weights)

    def test_no_desk_or_external_dependency(self):
        import application.quantitative.kpi_statistics as module
        source = inspect.getsource(module)
        for forbidden in ("InformationNeed", "EvidenceExpectation", "domain.sources", "openai", "tavily", "llm_client"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__": unittest.main()
