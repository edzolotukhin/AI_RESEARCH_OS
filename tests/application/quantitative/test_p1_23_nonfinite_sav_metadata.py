from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.state_persistence import QuantitativeStateService, encode_quantitative
from domain.quantitative.dataset import CodebookVersion, DatasetFormat
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)
from infrastructure.quantitative.importers.sav_pyreadstat_adapter import (
    SavPyreadstatAdapter,
    _canonical_user_missing,
    _canonical_value_labels,
)
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class P123NonFiniteSavMetadataTests(unittest.TestCase):
    def test_nonfinite_value_label_keys_are_excluded_with_diagnostics(self) -> None:
        labels, warnings = _canonical_value_labels(
            "choice",
            {
                float("nan"): "system artifact",
                float("inf"): "positive artifact",
                float("-inf"): "negative artifact",
                1.0: "finite",
            },
        )
        self.assertEqual(labels, ((1.0, "finite"),))
        self.assertEqual(
            warnings,
            (
                "sav_nonfinite_value_label_excluded:choice:NAN",
                "sav_nonfinite_value_label_excluded:choice:NEGATIVE_INFINITY",
                "sav_nonfinite_value_label_excluded:choice:POSITIVE_INFINITY",
            ),
        )

    def test_finite_numeric_and_string_categories_remain_unchanged(self) -> None:
        self.assertEqual(
            _canonical_value_labels("numeric", {2.0: "two", 1.0: "one"}),
            (((1.0, "one"), (2.0, "two")), ()),
        )
        self.assertEqual(
            _canonical_value_labels("string", {"B": "beta", "A": "alpha"}),
            ((("A", "alpha"), ("B", "beta")), ()),
        )

    def test_finite_user_missing_is_preserved_and_nonfinite_is_diagnostic(self) -> None:
        rules, warnings = _canonical_user_missing(
            "choice",
            ({"lo": 98.0, "hi": 99.0}, float("nan")),
        )
        self.assertEqual(rules, ({"lo": 98.0, "hi": 99.0},))
        self.assertEqual(
            warnings,
            ("sav_nonfinite_missing_metadata_excluded:choice:NAN",),
        )

    def test_unorderable_value_label_keys_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not canonically orderable"):
            _canonical_value_labels("mixed", {1.0: "one", "two": "two"})

    def test_adapter_import_and_state_round_trip_contain_no_nonfinite_metadata(self) -> None:
        metadata = SimpleNamespace(
            column_names=["DeviceId"],
            column_names_to_labels={"DeviceId": "Device"},
            variable_value_labels={
                "DeviceId": {float("nan"): "ambiguous", 388.0: "finite"}
            },
            missing_ranges={"DeviceId": [{"lo": 999.0, "hi": 999.0}]},
            variable_measure={"DeviceId": "nominal"},
            readstat_variable_types={"DeviceId": "double"},
            mr_sets={},
        )
        digest = Sha256DigestProvider()
        with patch(
            "infrastructure.quantitative.importers.sav_pyreadstat_adapter.pyreadstat.read_sav",
            return_value=({"DeviceId": [388.0, 999.0]}, metadata),
        ):
            imported = QuantitativeDatasetImportService(
                importers=(SavPyreadstatAdapter(),),
                storage=InMemoryDatasetStorage(),
                digest_provider=digest,
            ).import_bytes(
                b"synthetic-sav",
                filename="synthetic.sav",
                dataset_format=DatasetFormat.SAV,
                dataset_id="dataset",
                project_id="project",
                run_id="run",
            )

        variable = imported.codebook.variables[0]
        self.assertEqual(variable.value_labels, ((388.0, "finite"),))
        self.assertEqual(variable.missing_rules[0].low, 999.0)
        self.assertIn(
            "sav_nonfinite_value_label_excluded:DeviceId:NAN",
            imported.dataset_version.warnings,
        )
        encoded = repr(encode_quantitative(imported.codebook)).lower()
        self.assertNotIn("'$float': 'nan'", encoded)
        self.assertNotIn("'$float': 'inf'", encoded)
        self.assertNotIn("'$float': '-inf'", encoded)
        self.assertFalse(
            any(
                isinstance(value, float) and not math.isfinite(value)
                for pair in variable.value_labels
                for value in pair
                if not isinstance(value, str)
            )
        )

        state = QuantitativeStateService(
            repository=InMemoryQuantitativeStateRepository(),
            digest_provider=digest,
        )
        state.persist(
            imported.codebook,
            record_id="codebook",
            project_id="project",
            run_id="run",
            dataset_version_id=imported.dataset_version.version_id,
        )
        recovered = state.load(
            "codebook", project_id="project", expected_type=CodebookVersion
        )
        self.assertEqual(recovered, imported.codebook)


if __name__ == "__main__":
    unittest.main()