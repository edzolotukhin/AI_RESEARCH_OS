from __future__ import annotations

import unittest
from unittest.mock import patch
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from application.ports.quantitative_dataset_ports import ParsedDataset, ParsedVariable
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, QuantitativeImportError
from application.quantitative.dataset_limits import MAX_DATA_CELLS, MAX_DATA_ROWS, MAX_SOURCE_BYTES, MAX_VARIABLES
from domain.quantitative.dataset import DatasetFormat
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.quantitative.importers.sav_pyreadstat_adapter import SavPyreadstatAdapter
from infrastructure.quantitative.importers.xlsx_openpyxl_adapter import (
    MAX_XLSX_MEMBER_BYTES, MAX_XLSX_UNCOMPRESSED_BYTES, MAX_XLSX_ZIP_MEMBERS,
    XlsxOpenpyxlAdapter, _check_archive,
)
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class _ParsedImporter:
    format = DatasetFormat.XLSX

    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = 0

    def parse(self, data, *, filename, data_sheet=None):
        self.calls += 1
        return self.parsed


class Qnt02DatasetLimitsTests(unittest.TestCase):
    def _import(self, parsed, data=b"synthetic"):
        importer = _ParsedImporter(parsed)
        storage = InMemoryDatasetStorage()
        service = QuantitativeDatasetImportService(
            importers=(importer,), storage=storage, digest_provider=Sha256DigestProvider()
        )
        def invoke():
            return service.import_bytes(
                data, filename="fixture.xlsx", dataset_format=DatasetFormat.XLSX,
                dataset_id="dataset", project_id="project", run_id="run", data_sheet="Data"
            )
        return invoke, importer, storage

    @staticmethod
    def _parsed(variable_count, row_count, *, ragged=False):
        variables = tuple(ParsedVariable(name=f"v{i}") for i in range(variable_count))
        row = (1,) * variable_count
        rows = (row,) * row_count
        if ragged:
            rows = rows + (row[:-1],)
        return ParsedDataset(DatasetFormat.XLSX, variables, rows, "synthetic", "1")

    def test_source_size_rejected_before_parser_or_storage(self):
        invoke, importer, storage = self._import(self._parsed(1, 1), b"x" * (MAX_SOURCE_BYTES + 1))
        with self.assertRaises(QuantitativeImportError):
            invoke()
        self.assertEqual(importer.calls, 0)
        self.assertEqual(storage._manifests, {})

    def test_row_and_variable_bounds_rejected_before_storage(self):
        for parsed in (self._parsed(1, MAX_DATA_ROWS + 1), self._parsed(MAX_VARIABLES + 1, 1)):
            invoke, _, storage = self._import(parsed)
            with self.assertRaises(QuantitativeImportError):
                invoke()
            self.assertEqual(storage._manifests, {})

    def test_empty_and_ragged_rejected_before_storage(self):
        for parsed in (self._parsed(1, 0), self._parsed(0, 1), self._parsed(2, 1, ragged=True)):
            invoke, _, storage = self._import(parsed)
            with self.assertRaises(QuantitativeImportError):
                invoke()
            self.assertEqual(storage._manifests, {})

    def test_exact_row_and_variable_limits_are_accepted(self):
        for parsed in (self._parsed(1, MAX_DATA_ROWS), self._parsed(MAX_VARIABLES, 1)):
            invoke, _, storage = self._import(parsed)
            imported = invoke()
            self.assertEqual(storage.get_manifest(imported.dataset_version.version_id), imported.dataset_version)

    def test_cell_limit_exact_and_over(self):
        at_limit, _, _ = self._import(self._parsed(10, MAX_DATA_CELLS // 10))
        self.assertIsNotNone(at_limit().dataset_version)
        over_limit, _, storage = self._import(self._parsed(11, MAX_DATA_CELLS // 11 + 1))
        with self.assertRaises(QuantitativeImportError):
            over_limit()
        self.assertEqual(storage._manifests, {})

    def test_sav_metadata_rejects_before_full_materialization(self):
        with patch("infrastructure.quantitative.importers.sav_pyreadstat_adapter.pyreadstat.read_sav") as read:
            read.return_value = ({}, SimpleNamespace(number_rows=MAX_DATA_ROWS + 1, number_columns=1))
            with self.assertRaisesRegex(ValueError, "dimensions"):
                SavPyreadstatAdapter().parse(b"synthetic", filename="fixture.sav")
            self.assertEqual(read.call_count, 1)
            self.assertTrue(read.call_args.kwargs["metadataonly"])

    def test_sav_import_without_optional_pandas(self):
        with patch.dict(sys.modules, {"pandas": None}):
            parsed = SavPyreadstatAdapter().parse(
                sav_sample_bytes(), filename="fixture.sav"
            )
        self.assertEqual(len(parsed.variables), 7)
        self.assertEqual(len(parsed.rows), 5)

    def test_valid_xlsx_archive_still_imports(self):
        data = xlsx_bytes(["choice"], [["A"], ["B"]])
        self.assertEqual(XlsxOpenpyxlAdapter().parse(data, filename="fixture.xlsx", data_sheet="Data").rows,
                         (("A",), ("B",)))

    def test_xlsx_decompression_metadata_rejected_before_workbook_open(self):
        for members in (
            [SimpleNamespace(file_size=1, flag_bits=0)] * (MAX_XLSX_ZIP_MEMBERS + 1),
            [SimpleNamespace(file_size=MAX_XLSX_MEMBER_BYTES + 1, flag_bits=0)],
            [SimpleNamespace(file_size=MAX_XLSX_UNCOMPRESSED_BYTES // 3, flag_bits=0)] * 4,
            [SimpleNamespace(file_size=1, flag_bits=1)],
        ):
            archive = MagicMock()
            archive.__enter__.return_value.infolist.return_value = members
            with patch("infrastructure.quantitative.importers.xlsx_openpyxl_adapter.zipfile.ZipFile", return_value=archive), \
                 patch("infrastructure.quantitative.importers.xlsx_openpyxl_adapter.openpyxl.load_workbook") as load:
                with self.assertRaises(ValueError):
                    XlsxOpenpyxlAdapter().parse(b"synthetic", filename="fixture.xlsx")
                load.assert_not_called()
