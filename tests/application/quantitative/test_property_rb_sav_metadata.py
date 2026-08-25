import unittest

from application.ports.quantitative_dataset_ports import ParsedDataset, ParsedVariable
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from domain.quantitative.dataset import DatasetFormat, VariableType
from infrastructure.quantitative.importers.sav_pyreadstat_adapter import _mr_sets_by_variable


class PropertyRBSavMetadataTests(unittest.TestCase):
    def test_native_mr_metadata_is_preserved_and_absence_is_explicit(self):
        self.assertEqual(
            _mr_sets_by_variable({"$brands": {"variable_list": ["brand_a", "brand_b"]}}),
            {"brand_a": ("$brands",), "brand_b": ("$brands",)},
        )
        self.assertEqual(_mr_sets_by_variable({}), {})

    def test_labeled_scale_is_numeric_only_for_genuine_zero_to_ten_domain(self):
        rows=((0.0,1.0),(10.0,2.0))
        nps=ParsedVariable("nps",storage_type="double",measurement_level="scale",value_labels=tuple((float(i),str(i)) for i in range(11)))
        ordinary=ParsedVariable("rating",storage_type="double",measurement_level="scale",value_labels=((1.0,"Low"),(2.0,"High")))
        self.assertEqual(QuantitativeDatasetImportService._build_variables(ParsedDataset(DatasetFormat.SAV,(nps,),tuple((r[0],) for r in rows),"test","1"),{},digest_provider=__import__("infrastructure.security.sha256_digest_provider",fromlist=["Sha256DigestProvider"]).Sha256DigestProvider())[0].variable_type,VariableType.NUMERIC)
        self.assertEqual(QuantitativeDatasetImportService._build_variables(ParsedDataset(DatasetFormat.SAV,(ordinary,),tuple((r[1],) for r in rows),"test","1"),{},digest_provider=__import__("infrastructure.security.sha256_digest_provider",fromlist=["Sha256DigestProvider"]).Sha256DigestProvider())[0].variable_type,VariableType.CATEGORICAL)
