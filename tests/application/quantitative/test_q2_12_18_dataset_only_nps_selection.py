from __future__ import annotations

import unittest

from application.quantitative.stage_service_factory import QuantitativeStageServiceFactory
from domain.quantitative.dataset import (
    CodebookVersion,
    DatasetFormat,
    DatasetVersion,
    DatasetVersionKind,
    PiiClassification,
    ValidationStatus,
    VariableDefinition,
    VariableType,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class DatasetOnlyNpsSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = QuantitativeStageServiceFactory(
            state_service=object(),
            digest_provider=Sha256DigestProvider(),
            storage_factory=lambda _project, _run: object(),
            importers=(),
            finding_generator=object(),
            insight_generator=object(),
            report_generator=object(),
            generation_mode="offline",
        )
        self.dataset = DatasetVersion(
            "dataset", "dataset-v1", "project", "run", DatasetVersionKind.RAW,
            "source", "synthetic.sav", "file-fp", DatasetFormat.SAV, 12, 4,
            "schema-fp", "codebook-v1", "codebook-fp", "data-fp", "dataset-fp",
            PiiClassification.NONE, ValidationStatus.VALID, "protected", "test", "1",
        )
        self.categories = (
            VariableDefinition("cat-a", "cat_a", "A", VariableType.CATEGORICAL),
            VariableDefinition("cat-b", "cat_b", "B", VariableType.CATEGORICAL),
        )

    @staticmethod
    def numeric(variable_id: str) -> VariableDefinition:
        return VariableDefinition(variable_id, variable_id, variable_id, VariableType.NUMERIC, measurement_level="scale")

    @staticmethod
    def nps(variable_id: str) -> VariableDefinition:
        return VariableDefinition(
            variable_id,
            variable_id,
            variable_id,
            VariableType.NUMERIC,
            measurement_level="scale",
            value_labels=tuple((float(value), str(value)) for value in range(11)),
        )

    def plan(self, variables: tuple[VariableDefinition, ...]):
        codebook = CodebookVersion("codebook-v1", variables, "codebook-fp")
        return self.factory._build_plan(run_id="run", dataset=self.dataset, codebook=codebook)

    def test_unique_exact_domain_is_selected_separately_from_first_numeric(self):
        summary = self.numeric("summary")
        nps = self.nps("nps-source")
        plan = self.plan(self.categories + (summary, nps))
        self.assertEqual(plan.numeric.variable_id, summary.variable_id)
        self.assertEqual(plan.nps.variable_id, nps.variable_id)
        self.assertEqual(plan.questionnaire.answer_domains, ((nps.variable_id, tuple(range(11))),))

    def test_nps_selection_is_invariant_to_codebook_order(self):
        summary = self.numeric("summary")
        nps = self.nps("nps-source")
        first = self.plan(self.categories + (summary, nps))
        second = self.plan(self.categories + (nps, summary))
        self.assertEqual(first.nps.variable_id, second.nps.variable_id)

    def test_no_exact_domain_omits_optional_nps(self):
        plan = self.plan(self.categories + (self.numeric("summary"),))
        self.assertIsNone(plan.nps)
        self.assertEqual(plan.questionnaire.answer_domains, ())
        self.assertIsNotNone(plan.numeric)

    def test_multiple_exact_domains_omit_ambiguous_nps(self):
        first = self.plan(self.categories + (self.nps("nps-a"), self.nps("nps-b")))
        second = self.plan(self.categories + (self.nps("nps-b"), self.nps("nps-a")))
        self.assertIsNone(first.nps)
        self.assertIsNone(second.nps)
        self.assertEqual(first.questionnaire.answer_domains, ())
        self.assertEqual(second.questionnaire.answer_domains, ())


if __name__ == "__main__":
    unittest.main()
