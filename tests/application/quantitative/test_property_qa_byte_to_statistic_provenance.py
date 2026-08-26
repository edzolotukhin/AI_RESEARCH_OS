from __future__ import annotations

import inspect
import io
import re
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook

from application.ports.quantitative_dataset_ports import ParsedDataset, ParsedVariable
from application.quantitative.dataset_import_service import (
    QuantitativeDatasetImportService,
    QuantitativeImportError,
    VariableOverride,
)
from application.quantitative.one_way_statistics import (
    OneWayStatisticsService,
    QuantitativeAnalysisError,
)
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import (
    DatasetFormat,
    PiiClassification,
    ValidationStatus,
    VariableRole,
    VariableType,
)
from infrastructure.quantitative.importers import SavPyreadstatAdapter, XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class StubImporter:
    format = DatasetFormat.XLSX

    def __init__(self, parsed: ParsedDataset) -> None:
        self.parsed = parsed

    def parse(self, data: bytes, *, filename: str, data_sheet: str | None = None) -> ParsedDataset:
        return self.parsed


def xlsx_bytes(headers: list[str], rows: list[list[object]], *, formula: bool = False) -> bytes:
    workbook = Workbook()
    workbook.properties.created = datetime(2000, 1, 1)
    workbook.properties.modified = datetime(2000, 1, 1)
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    if formula:
        sheet["B2"] = "=1+1"
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    source = zipfile.ZipFile(io.BytesIO(output.getvalue()), "r")
    canonical = io.BytesIO()
    with source, zipfile.ZipFile(canonical, "w") as target:
        for member in sorted(source.infolist(), key=lambda item: item.filename):
            info = zipfile.ZipInfo(member.filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = member.compress_type
            info.comment = member.comment
            info.extra = member.extra
            info.internal_attr = member.internal_attr
            info.external_attr = member.external_attr
            info.create_system = member.create_system
            payload = source.read(member.filename)
            if member.filename == "docProps/core.xml":
                payload = re.sub(
                    rb"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
                    rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                    payload,
                )
            target.writestr(info, payload)
    return canonical.getvalue()


class PropertyQAByteToStatisticProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = InMemoryDatasetStorage()
        self.digest_provider = Sha256DigestProvider()

    def _xlsx_import(
        self,
        data: bytes,
        *,
        dataset_id: str = "dataset-xlsx",
        overrides: dict[str, VariableOverride] | None = None,
    ):
        service = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),),
            storage=self.storage,
            digest_provider=self.digest_provider,
        )
        return service.import_bytes(
            data,
            filename="survey.xlsx",
            dataset_format=DatasetFormat.XLSX,
            dataset_id=dataset_id,
            project_id="project-qa",
            run_id="run-qa",
            data_sheet="Data",
            overrides=overrides,
        )

    def _results(self, imported, variable_name: str, threshold: str = "1.0"):
        variable = next(item for item in imported.codebook.variables if item.name == variable_name)
        specification = AnalysisSpecification(
            specification_id=f"one-way-{variable.variable_id}",
            variable_id=variable.variable_id,
            presentation_threshold_percent=Decimal(threshold),
        )
        return OneWayStatisticsService(
            storage=self.storage,
            digest_provider=self.digest_provider,
        ).compute(
            dataset=imported.dataset_version,
            codebook=imported.codebook,
            specification=specification,
        )

    def test_a_valid_sav_categorical_import_preserves_labels(self) -> None:
        service = QuantitativeDatasetImportService(
            importers=(SavPyreadstatAdapter(),),
            storage=self.storage,
            digest_provider=self.digest_provider,
        )
        imported = service.import_bytes(
            sav_sample_bytes(),
            filename="sample.sav",
            dataset_format=DatasetFormat.SAV,
            dataset_id="dataset-sav",
            project_id="project-qa",
            run_id="run-qa",
        )
        labeled = next(item for item in imported.codebook.variables if item.name == "mylabl")
        self.assertEqual(labeled.label, "labeled")
        self.assertEqual(dict(labeled.value_labels), {1.0: "Male", 2.0: "Female"})
        self.assertEqual(imported.dataset_version.parser_name, "pyreadstat")

    def test_b_valid_xlsx_categorical_import(self) -> None:
        imported = self._xlsx_import(
            xlsx_bytes(["respondent_id", "choice"], [["r1", "A"], ["r2", "B"]]),
            overrides={
                "respondent_id": VariableOverride(
                    variable_type=VariableType.TECHNICAL_ID,
                    role=VariableRole.TECHNICAL_ID,
                )
            },
        )
        self.assertEqual(imported.dataset_version.row_count, 2)
        self.assertTrue(imported.dataset_version.weight_set_binding_supported)

    def test_c_numeric_mean_and_median(self) -> None:
        imported = self._xlsx_import(xlsx_bytes(["score"], [[1], [None], [2], [9]]))
        results = self._results(imported, "score")
        by_type = {item.statistic_type: item.value for item in results}
        self.assertEqual(by_type["VALID_N"], 3)
        self.assertEqual(by_type["MISSING_N"], 1)
        self.assertEqual(by_type["MEAN"], Decimal("4"))
        self.assertEqual(by_type["MEDIAN"], Decimal("2"))

    def test_d_declared_missing_and_undeclared_special_codes(self) -> None:
        data = xlsx_bytes(["score"], [[1], [98], [99], [None]])
        imported = self._xlsx_import(
            data,
            overrides={
                "score": VariableOverride(
                    variable_type=VariableType.CATEGORICAL,
                    missing_values=(99,),
                )
            },
        )
        results = self._results(imported, "score")
        counts = {
            item.category_value: item.value
            for item in results
            if item.statistic_type == "CATEGORY_COUNT"
        }
        self.assertEqual(counts, {1: 1, 98: 1})
        self.assertNotIn(99, counts)

    def test_e_unresolved_missing_conflict_blocks_results(self) -> None:
        parsed = ParsedDataset(
            format=DatasetFormat.XLSX,
            variables=(
                ParsedVariable(name="choice", user_missing=({"value": 99},)),
            ),
            rows=((1,), (99,)),
            parser_name="fixture",
            parser_version="1",
        )
        service = QuantitativeDatasetImportService(
            importers=(StubImporter(parsed),),
            storage=self.storage,
            digest_provider=self.digest_provider,
        )
        imported = service.import_bytes(
            b"fixture",
            filename="fixture.xlsx",
            dataset_format=DatasetFormat.XLSX,
            dataset_id="missing-conflict",
            project_id="project-qa",
            run_id="run-qa",
            overrides={
                "choice": VariableOverride(imported_missing_values_declared_valid=(99,))
            },
        )
        self.assertEqual(imported.dataset_version.validation_status, ValidationStatus.BLOCKED)
        with self.assertRaisesRegex(QuantitativeAnalysisError, "not analytically eligible"):
            self._results(imported, "choice")

    def test_f_same_rerun_has_identical_fingerprints_and_results(self) -> None:
        data = xlsx_bytes(["choice"], [["A"], ["B"], ["A"]])
        first = self._xlsx_import(data, dataset_id="repeat")
        second = self._xlsx_import(data, dataset_id="repeat")
        self.assertEqual(first.dataset_version, second.dataset_version)
        self.assertEqual(self._results(first, "choice"), self._results(second, "choice"))

    def test_g_changed_value_changes_data_and_dataset_fingerprint(self) -> None:
        first = self._xlsx_import(xlsx_bytes(["choice"], [["A"], ["B"]]), dataset_id="changed")
        second = self._xlsx_import(xlsx_bytes(["choice"], [["A"], ["C"]]), dataset_id="changed")
        self.assertNotEqual(first.dataset_version.data_fingerprint, second.dataset_version.data_fingerprint)
        self.assertNotEqual(first.dataset_version.dataset_fingerprint, second.dataset_version.dataset_fingerprint)

    def test_h_changed_codebook_changes_codebook_and_dataset_fingerprint(self) -> None:
        data = xlsx_bytes(["choice"], [[1], [2]])
        first = self._xlsx_import(
            data,
            dataset_id="codebook",
            overrides={"choice": VariableOverride(value_labels=((1, "Yes"), (2, "No")))},
        )
        second = self._xlsx_import(
            data,
            dataset_id="codebook",
            overrides={"choice": VariableOverride(value_labels=((1, "Agree"), (2, "Disagree")))},
        )
        self.assertNotEqual(first.dataset_version.codebook_fingerprint, second.dataset_version.codebook_fingerprint)
        self.assertNotEqual(first.dataset_version.dataset_fingerprint, second.dataset_version.dataset_fingerprint)

    def test_i_pii_is_restricted_and_cannot_be_result_dimension(self) -> None:
        imported = self._xlsx_import(
            xlsx_bytes(["respondent_name", "choice"], [["Alice", "A"], ["Bob", "B"]])
        )
        pii = next(item for item in imported.codebook.variables if item.name == "respondent_name")
        self.assertEqual(pii.pii_classification, PiiClassification.PII_RESTRICTED)
        self.assertNotIn("Alice", repr(imported.dataset_version))
        with self.assertRaisesRegex(QuantitativeAnalysisError, "not analytically eligible"):
            self._results(imported, "respondent_name")

    def test_j_pseudonymous_identity_and_duplicate_id_validation(self) -> None:
        override = {
            "respondent_id": VariableOverride(
                variable_type=VariableType.TECHNICAL_ID,
                role=VariableRole.TECHNICAL_ID,
            )
        }
        imported = self._xlsx_import(
            xlsx_bytes(["respondent_id"], [["secret-1"], ["secret-2"]]),
            overrides=override,
        )
        self.assertNotIn("secret-1", imported.analytical_respondent_ids)
        with self.assertRaisesRegex(QuantitativeImportError, "duplicate technical"):
            self._xlsx_import(
                xlsx_bytes(["respondent_id"], [["same"], ["same"]]),
                dataset_id="duplicates",
                overrides=override,
            )

    def test_k_no_stable_id_allows_import_but_blocks_weight_binding(self) -> None:
        imported = self._xlsx_import(xlsx_bytes(["choice"], [["A"], ["B"]]))
        self.assertFalse(imported.dataset_version.weight_set_binding_supported)
        self.assertEqual(len(imported.analytical_respondent_ids), 2)

    def test_l_all_categories_computed_and_threshold_is_presentation_only(self) -> None:
        rows = [["rare"]] + [["common"] for _ in range(99)]
        imported = self._xlsx_import(xlsx_bytes(["choice"], rows), dataset_id="threshold")
        results = self._results(imported, "choice")
        percentages = {
            item.category_value: item
            for item in results
            if item.statistic_type == "VALID_PERCENTAGE"
        }
        self.assertEqual(percentages["rare"].value, Decimal("1"))
        self.assertFalse(percentages["rare"].presentation_eligible)
        self.assertTrue(percentages["common"].presentation_eligible)
        self.assertEqual(
            len([item for item in results if item.statistic_type == "CATEGORY_COUNT"]),
            2,
        )

    def test_m_below_one_percent_retained_and_hidden(self) -> None:
        rows = [["rare"]] + [["common"] for _ in range(199)]
        imported = self._xlsx_import(xlsx_bytes(["choice"], rows), dataset_id="below")
        rare = next(
            item
            for item in self._results(imported, "choice")
            if item.statistic_type == "VALID_PERCENTAGE" and item.category_value == "rare"
        )
        self.assertEqual(rare.value, Decimal("0.5"))
        self.assertFalse(rare.presentation_eligible)

    def test_n_row_reorder_changes_data_fingerprint(self) -> None:
        first = self._xlsx_import(xlsx_bytes(["choice"], [["A"], ["B"]]), dataset_id="order")
        second = self._xlsx_import(xlsx_bytes(["choice"], [["B"], ["A"]]), dataset_id="order")
        self.assertNotEqual(first.dataset_version.data_fingerprint, second.dataset_version.data_fingerprint)

    def test_o_xlsx_formula_is_not_executed_and_warning_is_bounded(self) -> None:
        imported = self._xlsx_import(
            xlsx_bytes(["respondent_id", "calculated"], [["r1", 2]], formula=True),
            dataset_id="formula",
        )
        self.assertTrue(
            any(item.startswith("formula_stored_value_only:") for item in imported.dataset_version.warnings)
        )
        self.assertNotIn("=1+1", repr(imported.dataset_version))

    def test_p_system_missing_from_sav_is_excluded(self) -> None:
        service = QuantitativeDatasetImportService(
            importers=(SavPyreadstatAdapter(),),
            storage=self.storage,
            digest_provider=self.digest_provider,
        )
        imported = service.import_bytes(
            sav_sample_bytes(), filename="sample.sav", dataset_format=DatasetFormat.SAV,
            dataset_id="sav-missing", project_id="project-qa", run_id="run-qa"
        )
        results = self._results(imported, "mydate")
        by_type = {item.statistic_type: item.value for item in results}
        self.assertEqual(by_type["VALID_BASE"], 4)
        self.assertEqual(by_type["MISSING_COUNT"], 1)

    def test_q_quantitative_modules_have_no_desk_semantic_dependencies(self) -> None:
        import application.quantitative.dataset_import_service as import_service
        import application.quantitative.one_way_statistics as statistics

        source = inspect.getsource(import_service) + inspect.getsource(statistics)
        for forbidden in (
            "domain.sources",
            "domain.evidence",
            "InformationNeed",
            "EvidenceExpectation",
            "research_quality",
        ):
            self.assertNotIn(forbidden, source)

    def test_r_slice_has_no_provider_or_llm_path(self) -> None:
        import application.quantitative.dataset_import_service as import_service
        import application.quantitative.one_way_statistics as statistics

        source = (inspect.getsource(import_service) + inspect.getsource(statistics)).casefold()
        for forbidden in ("openai", "tavily", "llm_client", "provider.call"):
            self.assertNotIn(forbidden, source)

    def test_s_mixed_xlsx_types_require_explicit_mapping(self) -> None:
        data = xlsx_bytes(["mixed"], [[1], ["two"]])
        blocked = self._xlsx_import(data, dataset_id="mixed-blocked")
        self.assertEqual(blocked.dataset_version.validation_status, ValidationStatus.BLOCKED)
        with self.assertRaisesRegex(QuantitativeAnalysisError, "not analytically eligible"):
            self._results(blocked, "mixed")

        resolved = self._xlsx_import(
            data,
            dataset_id="mixed-resolved",
            overrides={"mixed": VariableOverride(variable_type=VariableType.CATEGORICAL)},
        )
        variable = resolved.codebook.variables[0]
        self.assertEqual(variable.validation_status, ValidationStatus.VALID_WITH_WARNINGS)
        self.assertTrue(self._results(resolved, "mixed"))


if __name__ == "__main__":
    unittest.main()
