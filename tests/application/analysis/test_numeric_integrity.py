from dataclasses import replace
import unittest

from application.analysis.numeric_integrity import (
    NumericIntegrityError,
    NumericObservationRequirements,
    evaluate_numeric_series,
    qualify_numeric_information_need,
    validate_numeric_observation,
)
from application.analysis import derivations
from application.research_quality import evidence_completeness_diagnostics
from tests.application.research_quality.test_evidence_completeness_diagnostics import (
    DESIGN, NEED, RUN, SUBJECT, SUBJECT_FINGERPRINT, evidence, source,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    EvidenceCoverageContract, InformationNeed, ResearchDesign, ResearchQuestion,
)
from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, SubjectResolutionStatus,
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


class CanonicalNumericQualificationTests(unittest.TestCase):
    def design(self, *, periods=("2019",), unit="persons"):
        subject = ResearchSubject(
            SUBJECT, "Population", "en", ("population",),
            (LexicalRepresentation(
                "population-en", "en", "Population", ("population",),
                ("population",), "fixture", "approved",
            ),),
            resolution_status=SubjectResolutionStatus.RESOLVED,
        )
        need = InformationNeed(
            NEED, "rq", "Population", geography="Ukraine",
            evidence_expectation=EvidenceExpectation(
                EvidenceNature.QUANTITATIVE,
                requires_quantitative_evidence=True,
            ),
            evidence_coverage=EvidenceCoverageContract(
                required_metric="Population", required_unit=unit,
                required_periods=periods, geography="Ukraine",
            ),
        )
        return ResearchDesign(DESIGN, (ResearchQuestion("rq", "Population"),),
            (need,), research_subject=subject)

    def qualify(self, sources, rows, *, design=None, temporal=None):
        design = design or self.design()
        source_by_id = {item.id: item for item in sources}
        class Repository:
            @staticmethod
            def get_by_id(identifier):
                return source_by_id.get(identifier)
        repository = Repository()
        fixed = []
        for item in rows:
            assignment = dict(item.metadata["semantic_assignment"])
            if (assignment.get("subject_id") == SUBJECT
                    and assignment.get("subject_fingerprint") == SUBJECT_FINGERPRINT):
                assignment.update(
                    subject_id=design.research_subject.subject_id,
                    subject_fingerprint=design.research_subject.semantic_fingerprint,
                )
            fixed.append(replace(item, metadata={
                **item.metadata, "semantic_assignment": assignment,
            }))
        decisions = temporal if temporal is not None else {
            (item.id, NEED): "applicable_satisfied" for item in fixed
        }
        return qualify_numeric_information_need(
            design=design, information_need=design.information_needs[0],
            evidence=fixed, source_repository=repository,
            temporal_decisions=decisions, allowed_workflow_run_ids=(RUN,),
        )

    def test_invalid_authority_and_temporal_inputs_are_rejected(self):
        item_source = source()
        base = evidence(item_source)
        cases = (
            replace(base, source_locator={**base.source_locator, "structured": {
                **base.source_locator["structured"], "terminal_resource_key": "forged",
            }}),
            evidence(item_source, subject_id="wrong"),
            evidence(item_source, geography="Poland"),
            evidence(item_source, period="2021"),
        )
        for item in cases:
            with self.subTest(item=item):
                result = self.qualify((item_source,), (item,))
                self.assertFalse(result.accepted_evidence)
                self.assertTrue(result.rejection_reason_counts)
        result = self.qualify((item_source,), (base,), temporal={})
        self.assertEqual(result.rejection_reason_counts, {"numeric_temporal_ineligible": 1})

    def test_missing_wrong_and_legacy_unit_fail_closed(self):
        item_source = source(); row = evidence(item_source)
        wrong = self.qualify((item_source,), (row,), design=self.design(unit="thousands"))
        self.assertEqual(wrong.rejection_reason_counts,
            {"numeric_unit_or_geography_binding_invalid": 1})
        payload = self.design().to_dict()
        del payload["information_needs"][0]["evidence_coverage"]["required_unit"]
        legacy = ResearchDesign.from_dict(payload)
        unavailable = self.qualify((item_source,), (row,), design=legacy)
        self.assertFalse(unavailable.available)
        self.assertEqual(unavailable.rejection_reason_counts,
            {"numeric_requirements_unavailable": 1})

    def test_conflicts_duplicates_periods_and_lineage_are_deterministic(self):
        first = source("s1", numeric="100")
        second = source("s2", numeric="101")
        conflict = self.qualify(
            (first, second),
            (evidence(first, identifier="e1", numeric="100"),
             evidence(second, identifier="e2", numeric="101")),
        )
        self.assertEqual(conflict.conflicting_periods, ("2019",))
        self.assertFalse(conflict.accepted_evidence)

        second = source("s2", numeric="100")
        duplicates = self.qualify(
            (first, second),
            (evidence(first, identifier="e1", numeric="100", lineage={"status":"established","origin_id":"mirror"}),
             evidence(second, identifier="e2", numeric="100", lineage={"status":"established","origin_id":"mirror"})),
        )
        self.assertEqual(duplicates.compatible_duplicate_periods, ("2019",))
        self.assertEqual(duplicates.established_lineage_ids, ("mirror",))
        self.assertEqual(len(duplicates.accepted_evidence), 2)

    def test_valid_independent_series_and_missing_periods(self):
        first = source("s1", "2019", numeric="100")
        second = source("s2", "2020", numeric="90")
        design = self.design(periods=("2019", "2020"))
        complete = self.qualify(
            (first, second),
            (evidence(first, "2019", identifier="e1", numeric="100"),
             evidence(second, "2020", identifier="e2", numeric="90")),
            design=design,
        )
        self.assertEqual(complete.qualified_periods, ("2019", "2020"))
        self.assertEqual(complete.missing_periods, ())
        incomplete = self.qualify(
            (first,), (evidence(first, "2019", identifier="e1", numeric="100"),),
            design=design,
        )
        self.assertEqual(incomplete.missing_periods, ("2020",))

    def test_more_than_one_hundred_evidence_fails_closed_without_partial_qualification(self):
        item_source = source()
        rows = tuple(
            evidence(item_source, identifier=f"evidence-{index:03d}")
            for index in range(101)
        )

        result = self.qualify((item_source,), rows)

        self.assertFalse(result.available)
        self.assertTrue(result.truncated)
        self.assertEqual(result.accepted_evidence, ())
        self.assertEqual(result.observations, ())
        self.assertEqual(result.qualified_periods, ())
        self.assertEqual(result.rejection_reason_counts,
            {"numeric_input_bound_exceeded": 101})


if __name__ == "__main__":
    unittest.main()
