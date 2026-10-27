from __future__ import annotations

import unittest

from application.report.claim_numeric_composition import (
    NumericCompositionError,
    build_fact_catalog,
    compose_assertion,
    render_numeric_fact,
)
from application.report.claim_rendering import validate_claim_proposition
from domain.reports.report_claim import NumericFact
from dataclasses import replace
import tests.application.report.test_report_claim_contract as fixtures


def fact(value="1.06", unit="млрд", scale="absolute", *, periods=("2021",),
         geography=("україна",), metrics=(), population=()):
    return NumericFact(value, unit, scale, geography, periods, metrics, population)


class ClaimNumericCompositionTests(unittest.TestCase):
    def catalog(self, *facts, periods=()):
        return build_fact_catalog(claim_id="claim-1", facts=tuple(facts), periods=tuple(periods))

    @staticmethod
    def assertion(*segments):
        return {"kind": "observation", "certainty": "direct", "direction": "not_applicable", "segments": list(segments)}

    def test_production_decimal_billion_preserves_period_and_passes_validator(self):
        selected = fact()
        catalog = self.catalog(selected)
        ref = next(iter(catalog.facts))
        assertion, facts = compose_assertion(self.assertion(
            {"type": "text", "text": "Обсяг становив "},
            {"type": "fact_ref", "fact_ref": ref},
            {"type": "text", "text": "."},
        ), catalog=catalog)
        self.assertEqual(assertion["proposition"], "Обсяг становив 1,06 млрд (період: 2021; географія: україна).")
        self.assertEqual(facts, (selected,))
        fixture = fixtures.ReportClaimContractTests(); fixture.setUp()
        claim = replace(fixture.claim(), proposition=assertion["proposition"], scope=replace(fixture.claim().scope, periods=("2021",), numeric_facts=facts))
        validate_claim_proposition(claim)

    def test_renderer_matrix(self):
        cases = (
            (fact("7.8", "%", periods=("2025",), geography=()), "7,8% (період: 2025)"),
            (fact("48705", "грн", periods=(), geography=()), "48\u202f705 грн"),
            (fact("10", "грн", "million", periods=(), geography=()), "10 млн грн"),
            (fact("10", "%", periods=(), geography=()), "10%"),
            (fact("5", "count", periods=("2026",), geography=("київ",), metrics=("sales",), population=("households",)),
             "5 count (період: 2026; географія: київ; показник: sales; група: households)"),
        )
        for numeric_fact, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(render_numeric_fact(numeric_fact), expected)

    def test_two_fact_comparison_keeps_independent_periods(self):
        first, second = fact("21", "%", periods=("2022",), geography=()), fact("6", "%", periods=("2025",), geography=())
        catalog = self.catalog(first, second)
        refs = list(catalog.facts)
        assertion, selected = compose_assertion(self.assertion(
            {"type": "text", "text": "Показник зменшився з "},
            {"type": "fact_ref", "fact_ref": refs[0]},
            {"type": "text", "text": " до "},
            {"type": "fact_ref", "fact_ref": refs[1]},
            {"type": "text", "text": "."},
        ), catalog=catalog)
        self.assertEqual(assertion["proposition"], "Показник зменшився з 21% (період: 2022) до 6% (період: 2025).")
        self.assertEqual(selected, (first, second))

    def test_period_ref_is_bounded_and_separate(self):
        catalog = self.catalog(periods=("2025",))
        ref = next(iter(catalog.periods))
        assertion, facts = compose_assertion(self.assertion(
            {"type": "text", "text": "Контекстний "}, {"type": "period_ref", "period_ref": ref},
        ), catalog=catalog)
        self.assertEqual(assertion["proposition"], "Контекстний період: 2025")
        self.assertEqual(facts, ())

    def test_all_numeric_text_leakage_fails(self):
        for text in ("1.06", "1,06", "7,8%", "2021", "48 705", "48\u00a0705", "10 млн", "-3.7%"):
            with self.subTest(text=text), self.assertRaises(NumericCompositionError) as captured:
                compose_assertion(self.assertion({"type": "text", "text": text}), catalog=self.catalog())
            self.assertEqual(captured.exception.diagnostics["validator_category"], "numeric_leakage")

    def test_segment_and_reference_fail_closed_matrix(self):
        catalog = self.catalog(fact())
        ref = next(iter(catalog.facts))
        foreign_same_claim = f"nf_{catalog.claim_key}_" + "0" * 64
        cases = (
            ([{"type": "unknown"}], "semantic_segment_schema"),
            ([{"type": "fact_ref", "fact_ref": "missing"}], "unknown_fact_ref"),
            ([{"type": "fact_ref", "fact_ref": foreign_same_claim}], "foreign_fact_ref"),
            ([{"type": "fact_ref", "fact_ref": "nf_foreign"}], "cross_claim_fact_ref"),
            ([{"type": "fact_ref", "fact_ref": ref}, {"type": "fact_ref", "fact_ref": ref}], "duplicate_fact_ref"),
            ([{"type": "period_ref", "period_ref": "missing"}], "period_ref_invalid"),
        )
        for segments, category in cases:
            with self.subTest(category=category), self.assertRaises(NumericCompositionError) as captured:
                compose_assertion(self.assertion(*segments), catalog=catalog)
            self.assertEqual(captured.exception.diagnostics["validator_category"], category)

    def test_fact_refs_are_deterministic_claim_bound_and_value_distinct(self):
        one = fact("1.06"); integer = fact("106")
        first = self.catalog(one, integer)
        second = self.catalog(one, integer)
        foreign = build_fact_catalog(claim_id="claim-2", facts=(one,), periods=())
        self.assertEqual(tuple(first.facts), tuple(second.facts))
        self.assertEqual(len(first.facts), 2)
        self.assertNotEqual(next(iter(first.facts)), next(iter(foreign.facts)))

    def test_fact_selection_and_semantic_relation_are_provider_controlled_but_fact_is_indivisible(self):
        first = fact("7.8", "%", periods=("2025",), geography=("україна",))
        second = fact("10", "%", periods=("2026",), geography=("україна",))
        catalog = self.catalog(first, second)
        ref = list(catalog.facts)[1]
        assertion = self.assertion(
            {"type": "text", "text": "Показник зріс до "},
            {"type": "fact_ref", "fact_ref": ref},
        )
        assertion["direction"] = "increase"
        composed, selected = compose_assertion(assertion, catalog=catalog)
        self.assertEqual("increase", composed["direction"])
        self.assertEqual((second,), selected)
        self.assertIn("10% (період: 2026; географія: україна)", composed["proposition"])


if __name__ == "__main__":
    unittest.main()
