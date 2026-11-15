from dataclasses import replace
import unittest

from application.analysis.numeric_integrity import (
    NumericIntegrityError,
    NumericObservationRequirements,
    evaluate_numeric_series,
    validate_numeric_observation,
)
from application.analysis import derivations
from application.research_quality import evidence_completeness_diagnostics
from tests.application.research_quality.test_evidence_completeness_diagnostics import (
    DESIGN, NEED, RUN, SUBJECT, SUBJECT_FINGERPRINT, evidence, source,
)


def requirements(**changes):
    values = dict(
        allowed_information_need_ids=(NEED,),
        subject_id=SUBJECT,
        subject_fingerprint=SUBJECT_FINGERPRINT,
        research_design_id=DESIGN,
        allowed_workflow_run_ids=(RUN,),
        metric="Population",
        unit="persons",
        geography="Ukraine",
        required_periods=("2019",),
    )
    values.update(changes)
    return NumericObservationRequirements(**values)


class NumericObservationValidityTests(unittest.TestCase):
    def test_derivations_and_i_a_use_the_same_f1_and_f2_functions(self):
        self.assertIs(derivations.validate_numeric_observation, validate_numeric_observation)
        self.assertIs(evidence_completeness_diagnostics.validate_numeric_observation, validate_numeric_observation)
        self.assertIs(derivations.evaluate_numeric_series, evaluate_numeric_series)
        self.assertIs(evidence_completeness_diagnostics.evaluate_numeric_series, evaluate_numeric_series)

    def validated(self, item_source=None, item_evidence=None, contract=None):
        item_source = item_source or source()
        item_evidence = item_evidence or evidence(item_source)
        return validate_numeric_observation(
            item_evidence, item_source, contract or requirements(), temporal_eligible=True,
        )

    def assert_rejected(self, code, item_source, item_evidence, contract=None):
        with self.assertRaisesRegex(NumericIntegrityError, f"^{code}$"):
            self.validated(item_source, item_evidence, contract)

    def test_valid_structured_numeric_observation(self):
        observation = self.validated()
        self.assertEqual((observation.period, str(observation.value)), ("2019", "100"))
        self.assertEqual(observation.subject_id, SUBJECT)
        self.assertTrue(observation.raw_content_checksum)

    def test_conflicting_unit_and_geography_cells(self):
        base = source()
        row = base.metadata["structured_tables_v2"][0]
        for cell in (
            {"cell": "E2", "header": "Units", "value": "thousands", "formula": False},
            {"cell": "E2", "header": "Country", "value": "Poland", "formula": False},
        ):
            with self.subTest(header=cell["header"]):
                changed = replace(base, metadata={"structured_tables_v2": [{**row, "cells": [*row["cells"], cell]}]})
                self.assert_rejected(
                    "numeric_unit_or_geography_binding_invalid", changed, evidence(changed),
                )

    def test_wrong_subject_id_and_fingerprint(self):
        item_source = source()
        for field in ("subject_id", "subject_fingerprint"):
            with self.subTest(field=field):
                item = evidence(item_source, **{field: "wrong"})
                self.assert_rejected("unvalidated_numeric_semantics", item_source, item)

    def test_wrong_dependency_ownership(self):
        item_source = source()
        item = evidence(item_source, assignment_need="foreign", needs=("foreign",))
        self.assert_rejected("numeric_semantic_dependency_mismatch", item_source, item)

    def test_incorrect_source_revision(self):
        item_source = source()
        item = evidence(item_source)
        changed = replace(item_source, terminal_resource_key="different-revision")
        self.assert_rejected("numeric_source_revision_mismatch", changed, item)

    def test_missing_required_provenance(self):
        item_source = source()
        item = evidence(item_source)
        changed = replace(item, metadata={k: v for k, v in item.metadata.items() if k != "workbook_provenance"})
        self.assert_rejected("numeric_source_revision_mismatch", item_source, changed)

    def test_temporal_ineligibility_fails_closed(self):
        item_source = source()
        with self.assertRaisesRegex(NumericIntegrityError, "^numeric_temporal_ineligible$"):
            validate_numeric_observation(evidence(item_source), item_source, requirements(), temporal_eligible=False)


class NumericSeriesIntegrityTests(unittest.TestCase):
    def observation(self, identifier, numeric):
        item_source = source(f"source-{identifier}", numeric=numeric)
        item = evidence(item_source, identifier=f"evidence-{identifier}", numeric=numeric)
        return validate_numeric_observation(item, item_source, requirements(), temporal_eligible=True)

    def test_compatible_duplicates_preserve_both_provenances(self):
        result = evaluate_numeric_series((self.observation("a", "100"), self.observation("b", "100.0")))
        self.assertEqual(result.conflicting_periods, ())
        self.assertEqual(result.compatible_duplicate_periods, ("2019",))
        self.assertEqual(str(result.values["2019"]), "100")
        self.assertEqual(len(result.observations_by_period["2019"]), 2)

    def test_conflicting_values_are_not_selected(self):
        result = evaluate_numeric_series((self.observation("a", "100"), self.observation("b", "101")))
        self.assertEqual(result.conflicting_periods, ("2019",))
        self.assertNotIn("2019", result.values)
        self.assertEqual(len(result.observations_by_period["2019"]), 2)

    def test_different_metric_or_scope_is_not_merged(self):
        base = self.observation("a", "100")
        for changed in (
            replace(base, metric="Employment"),
            replace(base, geography="Poland"),
            replace(base, subject_id="other-subject"),
        ):
            with self.subTest(changed=changed):
                result = evaluate_numeric_series((base, changed))
                self.assertEqual(result.conflicting_periods, ())
                self.assertNotIn("2019", result.values)
                self.assertEqual(len(result.observations_by_scope), 2)


if __name__ == "__main__":
    unittest.main()
