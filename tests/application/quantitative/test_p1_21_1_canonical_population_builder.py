from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from application.quantitative.finding_generation import (
    QuantitativeFindingGenerationService,
)
from application.quantitative.finding_lineage import (
    QuantitativeFindingLineageError,
    QuantitativeFindingLineageService,
)
from application.quantitative.finding_support import (
    QuantitativeFindingSupportValidator,
)
from domain.quantitative.dataset import (
    CodebookVersion,
    VariableDefinition,
    VariableType,
)
from domain.quantitative.finding import (
    QuantitativeClaim,
    QuantitativeClaimType,
    QuantitativeFinding,
    QuantitativeResultReference,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import (
    result,
)
from tests.application.quantitative import test_property_re_finding_lineage as re_tests


POPULATION = (
    "qualified power-tool users who completed the substantive "
    "Q43 attitudinal battery"
)
ANALYSES = (
    ("A1", "SL73R5", "77.84730913642053"),
    ("A2", "SL74R3", "77.2215269086358"),
    ("A3", "SL74R4", "76.9712140175219"),
    ("A4", "SL73R2", "52.19023779724657"),
    ("A5", "SL73R3", "42.052565707133915"),
)


class P1211CanonicalPopulationBuilderTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()
        self.service = QuantitativeFindingLineageService(
            repository=None,
            analysis_execution_repository=None,
            state_service=None,
            digest_provider=self.digest,
        )
        variables = tuple(
            VariableDefinition(
                variable_id=variable,
                name=variable,
                label=f"Q43 {analysis}",
                variable_type=VariableType.ORDINAL_SCALE,
                value_labels=(("4-5", "top-two-box agreement"),),
                fingerprint=f"variable-fp-{analysis.lower()}",
            )
            for analysis, variable, _ in ANALYSES
        )
        self.codebook = CodebookVersion(
            "study-3-codebook", variables, "study-3-codebook-fp"
        )
        self.manifest = SimpleNamespace(
            manifest_id="study-3-manifest",
            fingerprint="study-3-manifest-fp",
        )
        self.projection = SimpleNamespace(
            plan_id="study-3-plan",
            plan_fingerprint="study-3-plan-fp",
        )

    def authority(self, ordinal=0):
        analysis, variable, value = ANALYSES[ordinal]
        base = result(
            f"study-3-{analysis.lower()}",
            value,
            category="4-5",
            fingerprint=f"result-fp-{analysis.lower()}",
            filter_definition="Q43_SUBSTANTIVE",
        )
        return replace(
            base,
            variable_id=variable,
            variable_fingerprint=f"variable-fp-{analysis.lower()}",
            denominator=799,
            unweighted_n=799,
        )

    def context(self, ordinal=0, population=POPULATION):
        return self.service.semantic_context(
            result=self.authority(ordinal),
            codebook=self.codebook,
            manifest=self.manifest,
            projection=self.projection,
            population_description=population,
        )

    def supported_finding(self, ordinal, context):
        authority = self.authority(ordinal)
        text = QuantitativeFindingGenerationService._project_canonical_semantic_context(
            f"{context.display_value}% indicated agreement.", context
        )
        return QuantitativeFinding(
            finding_id=f"finding-{ordinal}",
            text=text,
            claim=QuantitativeClaim(
                claim_type=QuantitativeClaimType.DESCRIPTIVE_VALUE,
                value=authority.value,
                variable_id=authority.variable_id,
                statistic_type=authority.statistic_type,
                category_value=authority.category_value,
                filter_definition=authority.filter_definition,
                base_definition=authority.base_definition,
                weighting_status=authority.weighting_status,
                weight_set_fingerprint=authority.weight_set_fingerprint,
                display_value=context.display_value,
            ),
            statistical_result_refs=(
                QuantitativeResultReference(
                    authority.result_id, authority.reproducibility_fingerprint
                ),
            ),
            semantic_evidence_context=context,
        )

    def validate(self, ordinal, context):
        authority = self.authority(ordinal)
        return QuantitativeFindingSupportValidator(
            digest_provider=self.digest
        ).validate(
            self.supported_finding(ordinal, context),
            statistical_results={authority.result_id: authority},
            comparison_results={},
            semantic_evidence_contexts={authority.result_id: context},
        )

    def test_builder_without_population_preserves_historical_behavior(self):
        self.assertIsNone(self.context(population=None).population_description)

    def test_builder_stores_exact_population_authority(self):
        self.assertEqual(self.context().population_description, POPULATION)

    def test_builder_fingerprint_is_deterministic(self):
        self.assertEqual(self.context().fingerprint, self.context().fingerprint)

    def test_same_inputs_and_population_have_identical_contexts(self):
        self.assertEqual(self.context(), self.context())

    def test_different_population_authority_changes_fingerprint(self):
        self.assertNotEqual(
            self.context().fingerprint,
            self.context(population="qualified professional tool users").fingerprint,
        )

    def test_none_and_explicit_population_do_not_collide(self):
        self.assertNotEqual(
            self.context(population=None).fingerprint,
            self.context().fingerprint,
        )

    def test_integer_denominator_is_canonicalized_by_builder(self):
        context = self.context()
        self.assertEqual(context.denominator, 799)
        self.validate(0, context)

    def test_string_category_code_is_canonicalized_by_builder(self):
        context = self.context()
        self.assertEqual(context.category_code, "4-5")
        self.validate(0, context)

    def test_attitude_799_context_needs_no_manual_rehash_or_replace(self):
        context = self.context()
        self.assertEqual(context.population_description, POPULATION)
        self.assertEqual(context.denominator, 799)
        self.assertEqual(context.category_code, "4-5")
        self.assertEqual(context.weighting_status, "UNWEIGHTED")
        self.assertTrue(context.context_id.endswith(context.fingerprint))

    def test_all_five_study_3_contexts_pass_independent_validation(self):
        contexts = tuple(self.context(index) for index in range(5))
        validated = tuple(
            self.validate(index, context)
            for index, context in enumerate(contexts)
        )
        self.assertEqual(len(validated), 5)
        self.assertEqual(len({item.fingerprint for item in contexts}), 5)

    def test_corrupted_denominator_fails_closed(self):
        context = self.context()
        corrupted = replace(context, denominator=800)
        with self.assertRaisesRegex(
            Exception, "contradicts result authority|fingerprint mismatch"
        ):
            self.validate(0, corrupted)

    def test_corrupted_population_fails_closed(self):
        context = self.context()
        corrupted = replace(context, population_description="all respondents")
        with self.assertRaisesRegex(Exception, "fingerprint mismatch"):
            self.validate(0, corrupted)

    def test_build_input_authority_wires_population_by_result_id(self):
        fixture = re_tests.PropertyREFindingLineageTests(methodName="runTest")
        fixture.setUp()
        baseline = fixture.authority()
        eligible = next(
            item
            for item in baseline.analysis_entries
            if item.semantic_evidence_context is not None
        )
        enriched = fixture.authority(
            population_descriptions={eligible.result_id: POPULATION}
        )
        matching = next(
            item
            for item in enriched.analysis_entries
            if item.result_id == eligible.result_id
        )
        self.assertEqual(
            matching.semantic_evidence_context.population_description,
            POPULATION,
        )
        self.assertNotEqual(
            matching.semantic_evidence_context.fingerprint,
            eligible.semantic_evidence_context.fingerprint,
        )

    def test_invalid_population_authority_is_rejected(self):
        with self.assertRaisesRegex(
            QuantitativeFindingLineageError, "bounded validated text"
        ):
            self.context(population=" all respondents ")


if __name__ == "__main__":
    unittest.main()
