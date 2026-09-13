from __future__ import annotations

import unittest
from dataclasses import asdict, replace
from types import SimpleNamespace
from decimal import Decimal

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import fingerprint_analysis_specification
from application.quantitative.finding_lineage import QuantitativeFindingLineageService
from application.quantitative.one_way_statistics import OneWayStatisticsService, QuantitativeAnalysisError
from application.quantitative.weighted_one_way_statistics import WeightedOneWayStatisticsService
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from domain.quantitative.analysis import AnalysisSpecification, GroupedCategoryMetric, GroupedCategorySpecification
from domain.quantitative.dataset import DatasetFormat, VariableRole, VariableType
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes


class P122GroupedCategoryStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage()
        self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest)

    def imported(self, rows, *, weighted=False):
        headers = ["id", "score"] + (["weight"] if weighted else [])
        overrides = {"id": VariableOverride(role=VariableRole.TECHNICAL_ID), "score": VariableOverride(variable_type=VariableType.ORDINAL_SCALE)}
        if weighted:
            overrides["weight"] = VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT)
        return self.importer.import_bytes(xlsx_bytes(headers, rows), filename="grouped.xlsx", dataset_format=DatasetFormat.XLSX, dataset_id="p122", project_id="p122", run_id="p122", data_sheet="Data", overrides=overrides)

    def variable(self, imported, name="score"):
        return next(item for item in imported.codebook.variables if item.name == name)

    def group(self, members=(4, 5), metric=GroupedCategoryMetric.TOP_TWO_BOX_AGREEMENT):
        return GroupedCategorySpecification(tuple(members), "4-5", "ratings 4-5", metric)

    def spec(self, imported, *, group=True, weighted=False):
        return AnalysisSpecification("p122-spec", self.variable(imported).variable_id, weighting_status="WEIGHTED" if weighted else "UNWEIGHTED", grouped_category=self.group() if group else None)

    def test_unweighted_group_uses_counts_and_valid_base(self):
        imported = self.imported([["r1", 4], ["r2", 5], ["r3", 3], ["r4", None]])
        results = OneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.spec(imported))
        grouped = next(item for item in results if item.statistic_type == "GROUPED_CATEGORY_PERCENTAGE")
        self.assertEqual((grouped.numerator, grouped.denominator, grouped.value), (2, 3, Decimal(200) / Decimal(3)))
        self.assertEqual(grouped.grouped_category_members, (4, 5))
        self.assertEqual(grouped.grouped_metric_semantic, "TOP_TWO_BOX_AGREEMENT")

    def test_arbitrary_nonadjacent_group_is_generic(self):
        imported = self.imported([["r1", 1], ["r2", 2], ["r3", 3]])
        spec = replace(self.spec(imported), grouped_category=GroupedCategorySpecification((1, 3), "1+3", "ratings 1 and 3", GroupedCategoryMetric.GROUPED_PERCENTAGE))
        result = next(item for item in OneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=spec) if item.statistic_type == "GROUPED_CATEGORY_PERCENTAGE")
        self.assertEqual((result.numerator, result.denominator), (2, 3))

    def test_invalid_groups_fail_closed(self):
        imported = self.imported([["r1", 4], ["r2", 5]])
        cases = (
            GroupedCategorySpecification((), "4-5", "ratings", GroupedCategoryMetric.TOP_TWO_BOX),
            GroupedCategorySpecification((4, 4), "4-5", "ratings", GroupedCategoryMetric.TOP_TWO_BOX),
            GroupedCategorySpecification((5, 4), "4-5", "ratings", GroupedCategoryMetric.TOP_TWO_BOX),
            GroupedCategorySpecification((4, 5), 4, "ratings", GroupedCategoryMetric.TOP_TWO_BOX),
            GroupedCategorySpecification((4, 5), " 4-5", "ratings", GroupedCategoryMetric.TOP_TWO_BOX),
        )
        service = OneWayStatisticsService(storage=self.storage, digest_provider=self.digest)
        for group in cases:
            with self.subTest(group=group), self.assertRaises(QuantitativeAnalysisError):
                service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=replace(self.spec(imported), grouped_category=group))

    def test_unsupported_metric_type_fails_closed(self):
        imported = self.imported([["r1", 4], ["r2", 5]])
        group = GroupedCategorySpecification((4, 5), "4-5", "ratings", "BAD")  # type: ignore[arg-type]
        with self.assertRaises(QuantitativeAnalysisError):
            OneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=replace(self.spec(imported), grouped_category=group))

    def test_legacy_results_and_spec_fingerprint_are_unchanged(self):
        imported = self.imported([["r1", 4], ["r2", 5]])
        legacy = self.spec(imported, group=False)
        explicit_none = replace(legacy, grouped_category=None)
        self.assertEqual(fingerprint_analysis_specification(legacy, digest_provider=self.digest), fingerprint_analysis_specification(explicit_none, digest_provider=self.digest))
        results = OneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=legacy)
        self.assertNotIn("GROUPED_CATEGORY_PERCENTAGE", {item.statistic_type for item in results})

    def test_grouped_result_identity_is_repeatable(self):
        imported = self.imported([["r1", 4], ["r2", 5], ["r3", 3]])
        service = OneWayStatisticsService(storage=self.storage, digest_provider=self.digest)
        first = service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.spec(imported))
        second = service.compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=self.spec(imported))
        self.assertEqual(first, second)

    def test_grouped_specification_round_trip(self):
        original = self.group()
        payload = asdict(original)
        payload["member_categories"] = tuple(payload["member_categories"])
        payload["metric_semantic"] = GroupedCategoryMetric(payload["metric_semantic"])
        self.assertEqual(GroupedCategorySpecification(**payload), original)

    def test_study_3_numerical_oracle_and_semantic_fingerprints_repeat(self):
        numerators = (622, 617, 615, 417, 336)
        names = ("SL73R5", "SL74R3", "SL74R4", "SL73R2", "SL73R3")
        rows = []
        for index in range(799):
            rows.append([f"r{index}"] + [4 if index < numerator else 3 for numerator in numerators])
        overrides = {"id": VariableOverride(role=VariableRole.TECHNICAL_ID)}
        overrides.update({name: VariableOverride(variable_type=VariableType.ORDINAL_SCALE) for name in names})
        imported = self.importer.import_bytes(xlsx_bytes(["id", *names], rows), filename="study3.xlsx", dataset_format=DatasetFormat.XLSX, dataset_id="study3-p122", project_id="p122", run_id="study3", data_sheet="Data", overrides=overrides)
        lineage = QuantitativeFindingLineageService(repository=None, analysis_execution_repository=None, state_service=None, digest_provider=self.digest)
        manifest = SimpleNamespace(manifest_id="study3-rd", fingerprint="study3-rd-fp")
        projection = SimpleNamespace(plan_id="study3-plan", plan_fingerprint="study3-plan-fp")
        observed = []
        for name, numerator in zip(names, numerators):
            variable = self.variable(imported, name)
            spec = AnalysisSpecification(f"study3-{name}", variable.variable_id, filter_definition="Q43_SUBSTANTIVE", grouped_category=self.group())
            results = OneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=spec)
            result = next(item for item in results if item.statistic_type == "GROUPED_CATEGORY_PERCENTAGE")
            context1 = lineage.semantic_context(result=result, codebook=imported.codebook, manifest=manifest, projection=projection, population_description="qualified power-tool users who completed the substantive Q43 attitudinal battery")
            context2 = lineage.semantic_context(result=result, codebook=imported.codebook, manifest=manifest, projection=projection, population_description="qualified power-tool users who completed the substantive Q43 attitudinal battery")
            self.assertEqual((result.numerator, result.denominator), (numerator, 799))
            self.assertEqual(result.value, Decimal(numerator) * Decimal(100) / Decimal(799))
            self.assertEqual(context1, context2)
            observed.append((name, result.result_id, result.reproducibility_fingerprint, context1.fingerprint))
        self.assertEqual(len({item[3] for item in observed}), 5)

    def test_weighted_group_reuses_weighted_bases(self):
        imported = self.imported([["r1", 4, 1], ["r2", 5, 2], ["r3", 3, 1]], weighted=True)
        spec = self.spec(imported, weighted=True)
        weight_variable = self.variable(imported, "weight")
        weight_set = WeightImportService(storage=self.storage, digest_provider=self.digest).from_embedded_variable(dataset=imported.dataset_version, codebook=imported.codebook, variable_id=weight_variable.variable_id)
        approval = approve_weight_set(weight_set=weight_set, approver_id="manager", approved_at="2026-09-13T00:00:00Z", digest_provider=self.digest)
        quality = DatasetQualityAssessment(imported.dataset_version.version_id, imported.dataset_version.dataset_fingerprint, "qc", DatasetQualityState.QC_APPROVED, "manager", True, "approval")
        view = build_analytical_view(dataset=imported.dataset_version, quality=quality, specification=spec, mode=WeightingMode.WEIGHTED, respondent_refs=imported.analytical_respondent_ids, weight_set=weight_set, approval=approval, digest_provider=self.digest)
        results = WeightedOneWayStatisticsService(storage=self.storage, digest_provider=self.digest).compute(dataset=imported.dataset_version, codebook=imported.codebook, specification=spec, view=view, weight_set=weight_set)
        grouped = next(item for item in results if item.statistic_type == "GROUPED_CATEGORY_PERCENTAGE")
        self.assertEqual((grouped.numerator, grouped.denominator, grouped.value), (Decimal(3), Decimal(4), Decimal(75)))


if __name__ == "__main__":
    unittest.main()
