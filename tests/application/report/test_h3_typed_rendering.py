import ast
from dataclasses import replace
from pathlib import Path
import unittest

from application.report.typed_rendering import (
    H3AuthorityCatalog,
    H3_CONTRACT_VERSION,
    CitationAuthorityRef,
    ClaimAuthorityRef,
    FactAuthorityRef,
    InterpretationAuthorityRef,
    LimitationAuthorityRef,
    PeriodAuthorityRef,
    TypedRenderDocument,
    TypedRenderError,
    TypedRenderErrorCode,
    TypedRenderNode,
    TypedRenderNodeType,
    authority_input_digest,
    render_typed_document,
    rendered_output_digest,
    typed_ast_digest,
    validate_typed_render_document,
    verify_render_integrity,
)
from domain.reports.report_claim import NumericFact


def numeric(value="7.8", unit="%", scale="absolute", *, periods=("2025",),
            geography=("Україна",), metrics=("частка",), population=("домогосподарства",)):
    return NumericFact(value, unit, scale, geography, periods, metrics, population)


def catalog(*, first=None, second=None):
    first = first or numeric()
    facts = {"fact-a": FactAuthorityRef("fact-a", "claim-a", first)}
    periods = {
        "period-a": PeriodAuthorityRef("period-a", "claim-a", first.periods[0], "fact-a"),
        "period-standalone": PeriodAuthorityRef("period-standalone", "claim-a", "2026"),
    }
    claims = {"claim-a": ClaimAuthorityRef("claim-a", ("citation-a",))}
    citations = {"citation-a": CitationAuthorityRef("citation-a", "claim-a", "source-a", "S1")}
    if second is not None:
        facts["fact-b"] = FactAuthorityRef("fact-b", "claim-b", second)
        periods["period-b"] = PeriodAuthorityRef("period-b", "claim-b", second.periods[0], "fact-b")
        claims["claim-b"] = ClaimAuthorityRef("claim-b", ("citation-b",))
        citations["citation-b"] = CitationAuthorityRef("citation-b", "claim-b", "source-b", "S2")
    return H3AuthorityCatalog(
        claims=claims, facts=facts, periods=periods, citations=citations,
        limitations={"limit-a": LimitationAuthorityRef("limit-a", ("claim-a",), "Дані мають обмежене охоплення.")},
        interpretations={"interpret-a": InterpretationAuthorityRef("interpret-a", ("claim-a",), "increase", "Показник зріс")},
        forbidden_source_names=("Заборонене джерело",),
    )


def node(identity, kind, *, owner=None, ref=None, text=None, variant=None):
    return TypedRenderNode(identity, kind, owner, text, ref, variant)


def document(*nodes):
    return TypedRenderDocument(H3_CONTRACT_VERSION, "document-a", "report-a", tuple(nodes))


class H3TypedRenderingTests(unittest.TestCase):
    def test_numeric_authority_matrix(self):
        cases = (
            (numeric("48", "грн", periods=("2025",)), "48 грн"),
            (numeric("48.50", "грн", periods=("2025",)), "48,5 грн"),
            (numeric("7.8", "%", periods=("2025",)), "7,8%"),
            (numeric("10", "грн", "million", periods=("2025",)), "10 млн грн"),
            (numeric("-2.5", "%", periods=("2025",)), "-2,5%"),
        )
        for fact, expected in cases:
            with self.subTest(expected=expected):
                result = render_typed_document(document(node(
                    "n1", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a",
                )), catalog(first=fact))
                self.assertEqual(expected, result.text)
                self.assertTrue(verify_render_integrity(result))

    def test_fact_projection_variants_are_structural(self):
        authority = catalog()
        variants = (("geography", "Україна"), ("metric", "частка"), ("population", "домогосподарства"))
        for variant, expected in variants:
            with self.subTest(variant=variant):
                result = render_typed_document(document(node(
                    "n1", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a", variant=variant,
                )), authority)
                self.assertEqual(expected, result.text)

    def test_period_ownership_and_standalone_period(self):
        authority = catalog()
        result = render_typed_document(document(
            node("p1", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-a"),
            node("t", TypedRenderNodeType.TEXT, text="та"),
            node("p2", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-standalone", variant="locative"),
        ), authority)
        self.assertEqual("2025 та 2026 році", result.text)

    def test_multiple_fact_local_years_remain_explicit(self):
        authority = catalog(first=numeric(periods=("2024", "2025")))
        authority = H3AuthorityCatalog(
            claims=authority.claims, facts=authority.facts,
            periods={
                "period-a": PeriodAuthorityRef("period-a", "claim-a", "2024", "fact-a"),
                "period-b": PeriodAuthorityRef("period-b", "claim-a", "2025", "fact-a"),
            },
            citations=authority.citations, limitations=authority.limitations,
            interpretations=authority.interpretations,
        )
        result = render_typed_document(document(
            node("p1", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-a"),
            node("p2", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-b"),
        ), authority)
        self.assertEqual("2024 2025", result.text)

    def test_overlapping_periods_across_facts_remain_owned(self):
        authority = catalog(second=numeric("8.7", "%", periods=("2025",)))
        result = render_typed_document(document(
            node("a", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
            node("b", TypedRenderNodeType.FACT_REF, owner="claim-b", ref="fact-b"),
        ), authority)
        self.assertEqual("7,8% 8,7%", result.text)

    def test_boundary_matrix_is_authority_invariant(self):
        boundaries = (" ", "", ", ", ": ", " — ", " – ", " - ", "\n", "\u00a0", "\u202f", "(", ") ")
        authority = catalog()
        baseline = authority_input_digest(authority)
        for boundary in boundaries:
            with self.subTest(boundary=repr(boundary)):
                result = render_typed_document(document(
                    node("t1", TypedRenderNodeType.TEXT, text="Частка" + boundary),
                    node("f", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
                    node("t2", TypedRenderNodeType.TEXT, text="."),
                ), authority)
                self.assertIn("7,8%", result.text)
                self.assertEqual(baseline, result.authority_digest)

    def test_repeated_fact_and_period_are_preserved(self):
        result = render_typed_document(document(
            node("f1", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
            node("f2", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
            node("p1", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-a"),
            node("p2", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-a"),
        ), catalog())
        self.assertEqual("7,8% 7,8% 2025 2025", result.text)

    def test_repeated_citation_is_presented_once(self):
        result = render_typed_document(document(
            node("c1", TypedRenderNodeType.CITATION_REF, owner="claim-a", ref="citation-a"),
            node("c2", TypedRenderNodeType.CITATION_REF, owner="claim-a", ref="citation-a"),
        ), catalog())
        self.assertEqual("[S1]", result.text)

    def test_multiple_claims_and_references(self):
        authority = catalog(second=numeric("8.7", "%", periods=("2026",)))
        result = render_typed_document(document(
            node("ca", TypedRenderNodeType.CLAIM_REF, owner="claim-a", ref="claim-a"),
            node("fa", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
            node("fb", TypedRenderNodeType.FACT_REF, owner="claim-b", ref="fact-b"),
            node("cb", TypedRenderNodeType.CITATION_REF, owner="claim-b", ref="citation-b"),
        ), authority)
        self.assertEqual("7,8% 8,7%[S2]", result.text)

    def test_unknown_and_cross_owner_references_fail_closed(self):
        cases = (
            (node("x", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="missing"), TypedRenderErrorCode.UNKNOWN_FACT_REF),
            (node("x", TypedRenderNodeType.FACT_REF, owner="claim-b", ref="fact-a"), TypedRenderErrorCode.UNKNOWN_CLAIM_REF),
            (node("x", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="missing"), TypedRenderErrorCode.UNKNOWN_PERIOD_REF),
            (node("x", TypedRenderNodeType.CITATION_REF, owner="claim-a", ref="missing"), TypedRenderErrorCode.UNKNOWN_CITATION_REF),
            (node("x", TypedRenderNodeType.LIMITATION_REF, owner="claim-a", ref="invented"), TypedRenderErrorCode.UNKNOWN_LIMITATION_REF),
            (node("x", TypedRenderNodeType.INTERPRETATION_REF, owner="claim-a", ref="invented"), TypedRenderErrorCode.UNKNOWN_INTERPRETATION_REF),
            (node("x", TypedRenderNodeType.CLAIM_REF, owner="claim-a", ref="missing"), TypedRenderErrorCode.UNKNOWN_CLAIM_REF),
        )
        for value, code in cases:
            with self.subTest(code=code.value):
                with self.assertRaises(TypedRenderError) as captured:
                    validate_typed_render_document(document(value), catalog())
                self.assertEqual(code, captured.exception.code)

    def test_known_references_with_wrong_owner_fail_closed(self):
        authority = catalog(second=numeric("8.7", "%", periods=("2026",)))
        cases = (
            (node("f", TypedRenderNodeType.FACT_REF, owner="claim-b", ref="fact-a"), TypedRenderErrorCode.CROSS_CLAIM_FACT_REF),
            (node("p", TypedRenderNodeType.PERIOD_REF, owner="claim-b", ref="period-a"), TypedRenderErrorCode.CROSS_CLAIM_PERIOD_REF),
            (node("c", TypedRenderNodeType.CITATION_REF, owner="claim-b", ref="citation-a"), TypedRenderErrorCode.CROSS_CLAIM_CITATION_REF),
            (node("l", TypedRenderNodeType.LIMITATION_REF, owner="claim-b", ref="limit-a"), TypedRenderErrorCode.CROSS_CLAIM_LIMITATION_REF),
            (node("i", TypedRenderNodeType.INTERPRETATION_REF, owner="claim-b", ref="interpret-a"), TypedRenderErrorCode.CROSS_CLAIM_INTERPRETATION_REF),
        )
        for value, code in cases:
            with self.subTest(code=code.value):
                with self.assertRaises(TypedRenderError) as captured:
                    validate_typed_render_document(document(value), authority)
                self.assertEqual(code, captured.exception.code)

    def test_fact_local_period_cannot_migrate(self):
        authority = catalog()
        mutated = H3AuthorityCatalog(
            claims=authority.claims, facts=authority.facts,
            periods={"period-a": PeriodAuthorityRef("period-a", "claim-a", "2026", "fact-a")},
            citations=authority.citations, limitations=authority.limitations,
            interpretations=authority.interpretations,
        )
        with self.assertRaises(TypedRenderError) as captured:
            validate_typed_render_document(document(node(
                "p", TypedRenderNodeType.PERIOD_REF, owner="claim-a", ref="period-a",
            )), mutated)
        self.assertEqual(TypedRenderErrorCode.FACT_LOCAL_PERIOD_MISMATCH, captured.exception.code)

    def test_unsupported_citation_fails_closed(self):
        authority = catalog()
        mutated = H3AuthorityCatalog(
            claims={"claim-a": ClaimAuthorityRef("claim-a", ())}, facts=authority.facts,
            periods=authority.periods, citations=authority.citations,
            limitations=authority.limitations, interpretations=authority.interpretations,
        )
        with self.assertRaises(TypedRenderError) as captured:
            validate_typed_render_document(document(node(
                "c", TypedRenderNodeType.CITATION_REF, owner="claim-a", ref="citation-a",
            )), mutated)
        self.assertEqual(TypedRenderErrorCode.UNSUPPORTED_CITATION_REF, captured.exception.code)

    def test_text_safety_matrix(self):
        cases = (
            ("значення 7", TypedRenderErrorCode.TEXT_DIGIT_LEAKAGE),
            ("див. https://example.com", TypedRenderErrorCode.TEXT_URL_LEAKAGE),
            ("claim_internal", TypedRenderErrorCode.TEXT_INTERNAL_ID_LEAKAGE),
            ("Заборонене джерело повідомляє", TypedRenderErrorCode.TEXT_SOURCE_NAME_LEAKAGE),
            ("період: рік", TypedRenderErrorCode.TEXT_FACT_ANNOTATION_LEAKAGE),
        )
        for text, code in cases:
            with self.subTest(code=code.value):
                with self.assertRaises(TypedRenderError) as captured:
                    validate_typed_render_document(document(node("t", TypedRenderNodeType.TEXT, text=text)), catalog())
                self.assertEqual(code, captured.exception.code)
        render_typed_document(document(node("t", TypedRenderNodeType.TEXT, text="Український текст — безпечний!")), catalog())

    def test_interpretation_cannot_introduce_numbers(self):
        authority = catalog()
        mutated = H3AuthorityCatalog(
            claims=authority.claims, facts=authority.facts, periods=authority.periods,
            citations=authority.citations, limitations=authority.limitations,
            interpretations={"interpret-a": InterpretationAuthorityRef("interpret-a", ("claim-a",), "increase", "Зростання на 7 відсотків")},
        )
        with self.assertRaises(TypedRenderError) as captured:
            validate_typed_render_document(document(node(
                "i", TypedRenderNodeType.INTERPRETATION_REF, owner="claim-a", ref="interpret-a",
            )), mutated)
        self.assertEqual(TypedRenderErrorCode.TEXT_DIGIT_LEAKAGE, captured.exception.code)

    def test_duplicate_node_identity_is_rejected(self):
        with self.assertRaises(TypedRenderError) as captured:
            validate_typed_render_document(document(
                node("same", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
                node("same", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
            ), catalog())
        self.assertEqual(TypedRenderErrorCode.DUPLICATE_NODE_ID, captured.exception.code)

    def test_serialization_rendering_and_digests_are_deterministic(self):
        authority = catalog()
        value = document(
            node("t", TypedRenderNodeType.TEXT, text="Частка становить"),
            node("f", TypedRenderNodeType.FACT_REF, owner="claim-a", ref="fact-a"),
        )
        first = render_typed_document(value, authority)
        second = render_typed_document(value, authority)
        self.assertEqual(first, second)
        self.assertEqual(typed_ast_digest(value), typed_ast_digest(value))
        self.assertEqual(authority_input_digest(authority), authority_input_digest(authority))
        self.assertEqual(first.render_digest, rendered_output_digest(
            text=first.text, locale=first.locale, renderer_version=first.renderer_version,
        ))

        changed_ast = replace(value, nodes=value.nodes + (node("x", TypedRenderNodeType.TEXT, text="."),))
        self.assertNotEqual(typed_ast_digest(value), typed_ast_digest(changed_ast))
        changed_authority = catalog(first=numeric("8.7", "%", periods=("2025",)))
        self.assertNotEqual(authority_input_digest(authority), authority_input_digest(changed_authority))
        self.assertNotEqual(first.render_digest, rendered_output_digest(
            text=first.text, locale=first.locale, renderer_version="desk_h3_uk_v2",
        ))

    def test_authority_digest_ignores_mapping_insertion_order(self):
        authority = catalog(second=numeric("8.7", "%", periods=("2026",)))
        reordered = H3AuthorityCatalog(
            claims=dict(reversed(tuple(authority.claims.items()))),
            facts=dict(reversed(tuple(authority.facts.items()))),
            periods=dict(reversed(tuple(authority.periods.items()))),
            citations=dict(reversed(tuple(authority.citations.items()))),
            limitations=authority.limitations,
            interpretations=authority.interpretations,
            forbidden_source_names=authority.forbidden_source_names,
        )
        self.assertEqual(authority_input_digest(authority), authority_input_digest(reordered))

    def test_h3_authority_path_does_not_reparse_rendered_prose(self):
        module_path = Path(__file__).parents[3] / "application" / "report" / "typed_rendering.py"
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_imports = {
            "application.research_scope.numeric_normalization",
            "application.report.claim_scope_validation",
        }
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom):
                self.assertNotIn(item.module, forbidden_imports)
        forbidden_calls = {"extract_numeric_tokens", "rendered_facts", "validate_claim_scope"}
        for item in ast.walk(tree):
            if isinstance(item, ast.Call):
                name = item.func.id if isinstance(item.func, ast.Name) else (
                    item.func.attr if isinstance(item.func, ast.Attribute) else ""
                )
                self.assertNotIn(name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
