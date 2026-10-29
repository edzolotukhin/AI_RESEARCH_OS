from __future__ import annotations

from dataclasses import replace
import copy
import json
import re
import unittest

from application.report.editorial_composer import (
    EditorialComposer,
    EditorialCompositionError,
    FactDisplayVariant,
    GeographyDisplayVariant,
    PeriodDisplayVariant,
    build_editorial_options,
    build_provider_request,
    parse_editorial_proposal,
    render_coverage_limitation,
    render_presentation_fact,
    render_presentation_geography,
    render_presentation_period,
    LlmEditorialProposalProvider,
)
from application.report.editorial_contract import (
    CoverageLimitation,
    CoverageStatus,
    EvidenceRequirementLabel,
    ImpactLabel,
    MissingDimension,
    PresentationQualifier,
    build_authorized_editorial_catalog,
)
from domain.reports.report_claim import ClaimScope, NumericFact
from domain.ai.llm_response import LLMResponse
from tests.application.report.test_editorial_contract import claim, numeric


class FakeEditorialProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(copy.deepcopy(request))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


def multi_fact_claim(claim_id, facts, *, rq, citation, source, direction="mixed"):
    base = claim(claim_id, facts[0], rq=rq, citation=citation, source=source, direction=direction)
    scope = ClaimScope(
        tuple(sorted({geo for fact in facts for geo in fact.geography})), (),
        tuple(sorted({period for fact in facts for period in fact.periods})),
        tuple(sorted({metric for fact in facts for metric in fact.metrics})),
        tuple(sorted({dimension for fact in facts for dimension in fact.population_dimensions})), tuple(facts),
    )
    return replace(base, scope=scope, kind="comparison")


class EditorialComposerTests(unittest.TestCase):
    def setUp(self):
        april = claim("claim-april", numeric("7.8", "%", "2026-04"), citation="S1", source="source-1")
        ytd = claim("claim-ytd", numeric("8.7", "%", "2026-01/2026-04"), citation="S1", source="source-1")
        baseline = claim("claim-2021", numeric("1.064", "USD", "2021", "оцінений обсяг електронної торгівлі", scale="billion"), rq="rq3_channel", citation="S2", source="source-2")
        forecast = claim("claim-2025", numeric("7", "USD", "2025", "прогнозований обсяг електронної торгівлі", scale="billion"), rq="rq3_channel", citation="S3", source="source-3")
        share = claim("claim-share", numeric("10", "%", "2025", "частка електронної торгівлі"), rq="rq3_channel", citation="S3", source="source-3")
        benchmark = multi_fact_claim(
            "claim-benchmark",
            (
                NumericFact("10", "%", "absolute", ("україна",), ("2025",), ("частка електронної торгівлі",), ()),
                NumericFact("20.1", "%", "absolute", ("польща",), ("2025",), ("частка електронної торгівлі",), ()),
            ), rq="rq3_channel", citation="S4", source="source-4",
        )
        categories = multi_fact_claim(
            "claim-categories",
            (
                NumericFact("36", "%", "absolute", ("україна",), ("2025",), ("частка категорії",), ("електроніка",)),
                NumericFact("23", "%", "absolute", ("україна",), ("2025",), ("частка категорії",), ("одяг",)),
            ), rq="rq3_channel", citation="S5", source="source-5",
        )
        self.claims = (april, ytd, baseline, forecast, share, benchmark, categories)
        self.registry = {
            "S1": {"source_id": "source-1", "title": "Офіційна статистика торгівлі", "canonical_url": "https://example.test/retail"},
            "S2": {"source_id": "source-2", "title": "Базова оцінка електронної торгівлі", "canonical_url": "https://example.test/base"},
            "S3": {"source_id": "source-3", "title": "Прогноз електронної торгівлі", "canonical_url": "https://example.test/forecast"},
            "S4": {"source_id": "source-4", "title": "Міжнародне зіставлення", "canonical_url": "https://example.test/benchmark"},
            "S5": {"source_id": "source-5", "title": "Категорійна структура", "canonical_url": "https://example.test/category"},
        }
        initial = build_authorized_editorial_catalog(self.claims, citation_registry=self.registry)
        limitation = CoverageLimitation(
            "lim-series", "market_trajectory", ("claim-april", "claim-ytd"),
            initial.claims["claim-april"].period_refs + initial.claims["claim-ytd"].period_refs,
            (MissingDimension.PERIOD,), ("2022", "2023", "2024", "2025"),
            CoverageStatus.INCOMPLETE_SERIES, ImpactLabel.LIMITS_TREND_INFERENCE,
            (EvidenceRequirementLabel.ADDITIONAL_PERIODS,),
        )
        qualifiers = {
            initial.claims["claim-2021"].fact_refs[0]: PresentationQualifier.APPROXIMATE,
            initial.claims["claim-2025"].fact_refs[0]: PresentationQualifier.GREATER_THAN,
            initial.claims["claim-share"].fact_refs[0]: PresentationQualifier.APPROXIMATE,
        }
        self.catalog = build_authorized_editorial_catalog(
            self.claims, citation_registry=self.registry, limitations=(limitation,), fact_qualifiers=qualifiers,
        )
        self.options = build_editorial_options(self.catalog)
        self.valid = self.valid_payload()

    def fact_ref(self, claim_ref, index=0):
        return self.catalog.claims[claim_ref].fact_refs[index]

    def period_ref(self, claim_ref, index=0):
        return self.catalog.claims[claim_ref].period_refs[index]

    def interpretation_ref(self, claim_ref, label="increase"):
        return next(ref for ref, value in self.options.interpretations.items() if value[0] == (claim_ref,) and value[1].value == label)

    def trend_group_ref(self, left="claim-april", right="claim-ytd"):
        return next(ref for ref, group in self.options.groups.items() if set(group.claim_refs) == {left, right} and group.relation.value == "trend")

    def valid_payload(self):
        trend = self.trend_group_ref()
        increase = self.interpretation_ref("claim-april")
        return {
            "contract_version": "desk_editorial_v1",
            "report_title": "Огляд роздрібної торгівлі України",
            "executive_summary": [
                {"paragraph_id": "summary-trajectory", "group_refs": [trend], "segments": [
                    {"type": "TEXT", "text": "У "},
                    {"type": "PERIOD_REF", "claim_ref": "claim-april", "period_ref": self.period_ref("claim-april"), "variant": "locative"},
                    {"type": "METRIC_REF", "claim_ref": "claim-april", "fact_ref": self.fact_ref("claim-april")},
                    {"type": "INTERPRETATION_REF", "interpretation_ref": increase, "text": "зріс на"},
                    {"type": "FACT_REF", "claim_ref": "claim-april", "fact_ref": self.fact_ref("claim-april"), "variant": "value_with_unit"},
                    {"type": "TEXT", "text": "."},
                ]},
                {"paragraph_id": "summary-limit", "group_refs": [], "segments": [
                    {"type": "LIMITATION_REF", "limitation_ref": "lim-series"},
                ]},
            ],
            "sections": [
                {"section_id": "market-trajectory", "title": "Динаміка роздрібного ринку", "purpose": "Підтверджена зміна показників", "paragraphs": [
                    {"paragraph_id": "trajectory-detail", "group_refs": [trend], "segments": [
                        {"type": "TEXT", "text": "У "},
                        {"type": "PERIOD_REF", "claim_ref": "claim-april", "period_ref": self.period_ref("claim-april"), "variant": "locative"},
                        {"type": "TEXT", "text": " показник становив "},
                        {"type": "FACT_REF", "claim_ref": "claim-april", "fact_ref": self.fact_ref("claim-april"), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": ", а за "},
                        {"type": "PERIOD_REF", "claim_ref": "claim-ytd", "period_ref": self.period_ref("claim-ytd"), "variant": "genitive_range"},
                        {"type": "TEXT", "text": " — "},
                        {"type": "FACT_REF", "claim_ref": "claim-ytd", "fact_ref": self.fact_ref("claim-ytd"), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": "."},
                    ]},
                ]},
                {"section_id": "channel-shift", "title": "Розвиток електронної торгівлі", "purpose": "Підтверджені зміни каналу продажів", "paragraphs": [
                    {"paragraph_id": "ecommerce-scale", "group_refs": [], "segments": [
                        {"type": "TEXT", "text": "У "},
                        {"type": "PERIOD_REF", "claim_ref": "claim-2021", "period_ref": self.period_ref("claim-2021"), "variant": "locative"},
                        {"type": "METRIC_REF", "claim_ref": "claim-2021", "fact_ref": self.fact_ref("claim-2021")},
                        {"type": "TEXT", "text": " становив "},
                        {"type": "FACT_REF", "claim_ref": "claim-2021", "fact_ref": self.fact_ref("claim-2021"), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": ", а у "},
                        {"type": "PERIOD_REF", "claim_ref": "claim-2025", "period_ref": self.period_ref("claim-2025"), "variant": "locative"},
                        {"type": "METRIC_REF", "claim_ref": "claim-2025", "fact_ref": self.fact_ref("claim-2025")},
                        {"type": "TEXT", "text": " становить "},
                        {"type": "FACT_REF", "claim_ref": "claim-2025", "fact_ref": self.fact_ref("claim-2025"), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": "."},
                    ]},
                    {"paragraph_id": "ecommerce-share", "group_refs": [], "segments": [
                        {"type": "TEXT", "text": "Підтверджена частка каналу становить "},
                        {"type": "FACT_REF", "claim_ref": "claim-share", "fact_ref": self.fact_ref("claim-share"), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": "."},
                    ]},
                    {"paragraph_id": "ecommerce-benchmark", "group_refs": [], "segments": [
                        {"type": "GEOGRAPHY_REF", "claim_ref": "claim-benchmark", "fact_ref": self.fact_ref("claim-benchmark", 0), "variant": "locative_with_preposition"},
                        {"type": "TEXT", "text": " показник становить "},
                        {"type": "FACT_REF", "claim_ref": "claim-benchmark", "fact_ref": self.fact_ref("claim-benchmark", 0), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": ", а у "},
                        {"type": "GEOGRAPHY_REF", "claim_ref": "claim-benchmark", "fact_ref": self.fact_ref("claim-benchmark", 1), "variant": "locative"},
                        {"type": "TEXT", "text": " — "},
                        {"type": "FACT_REF", "claim_ref": "claim-benchmark", "fact_ref": self.fact_ref("claim-benchmark", 1), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": "."},
                    ]},
                    {"paragraph_id": "ecommerce-categories", "group_refs": [], "segments": [
                        {"type": "POPULATION_REF", "claim_ref": "claim-categories", "fact_ref": self.fact_ref("claim-categories", 0), "variant": "sentence_start"},
                        {"type": "TEXT", "text": " формує "},
                        {"type": "FACT_REF", "claim_ref": "claim-categories", "fact_ref": self.fact_ref("claim-categories", 0), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": ", а "},
                        {"type": "POPULATION_REF", "claim_ref": "claim-categories", "fact_ref": self.fact_ref("claim-categories", 1), "variant": "nominative"},
                        {"type": "TEXT", "text": " — "},
                        {"type": "FACT_REF", "claim_ref": "claim-categories", "fact_ref": self.fact_ref("claim-categories", 1), "variant": "value_with_unit"},
                        {"type": "TEXT", "text": "."},
                    ]},
                ]},
            ],
        }

    def compose(self, *responses):
        provider = FakeEditorialProvider(*responses)
        result = EditorialComposer(provider).compose(
            report_id="report-1", revision_number=2, source_report_id="source-report-1",
            authority_digest="authority-digest", catalog=self.catalog,
        )
        return result, provider

    def failure(self, payload, repair=None):
        provider = FakeEditorialProvider(payload, copy.deepcopy(payload) if repair is None else repair)
        with self.assertRaises(EditorialCompositionError) as captured:
            EditorialComposer(provider).compose(
                report_id="report-1", revision_number=1, source_report_id="source-report-1",
                authority_digest="authority-digest", catalog=self.catalog,
            )
        return captured.exception, provider

    # Provider schema
    def test_valid_provider_proposal_accepted(self):
        result, _ = self.compose(self.valid)
        self.assertEqual("desk_editorial_v1", result.report.contract_version)

    def test_unknown_provider_field_rejected(self):
        payload = copy.deepcopy(self.valid); payload["invented"] = True
        error, _ = self.failure(payload)
        self.assertEqual("proposal_schema", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_wrong_provider_contract_version_rejected(self):
        payload = copy.deepcopy(self.valid); payload["contract_version"] = "wrong"
        error, _ = self.failure(payload)
        self.assertEqual("unsupported_contract_version", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_segment_additional_field_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][0]["extra"] = "x"
        error, _ = self.failure(payload)
        self.assertEqual("segment_schema", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_unknown_authority_refs_rejected_matrix(self):
        cases = (
            ("claim_ref", "claim-missing", "unknown_claim_ref"),
            ("fact_ref", "nf-missing", "unknown_fact_ref"),
            ("period_ref", "ep-missing", "unknown_period_ref"),
        )
        for field, value, code in cases:
            with self.subTest(code=code):
                payload = copy.deepcopy(self.valid)
                segment = payload["sections"][0]["paragraphs"][0]["segments"][1 if field == "period_ref" else 3]
                segment[field] = value
                error, _ = self.failure(payload)
                self.assertIn(code, error.diagnostics["attempts"][0]["validation_codes"])

    def test_unknown_citation_rejected(self):
        payload = copy.deepcopy(self.valid)
        payload["sections"][0]["paragraphs"][0]["segments"].append({"type": "CITATION_REF", "claim_ref": "claim-april", "citation_ref": "ec-missing"})
        error, _ = self.failure(payload)
        self.assertEqual("unknown_citation_ref", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_unknown_group_rejected(self):
        payload = copy.deepcopy(self.valid); payload["sections"][0]["paragraphs"][0]["group_refs"] = ["eg-missing"]
        error, _ = self.failure(payload)
        self.assertEqual("unknown_claim_group", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_unknown_interpretation_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][3]["interpretation_ref"] = "ei-missing"
        error, _ = self.failure(payload)
        self.assertEqual("unknown_interpretation", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_unknown_limitation_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][1]["segments"][0]["limitation_ref"] = "lim-missing"
        error, _ = self.failure(payload)
        self.assertEqual("unknown_limitation", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_provider_text_leakage_matrix(self):
        cases = (("Ринок зріс на 12", "text_digit_leakage"), ("Події 2026 року", "text_digit_leakage"), ("Джерело https://bad.test", "url_leakage"), ("Дані source-1", "internal_id_leakage"), ("Висновок rq1_trajectory", "internal_id_leakage"), ("Значення (період: квітень)", "h2_annotation_leakage"))
        for text, code in cases:
            with self.subTest(code=code):
                payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][0]["text"] = text
                error, _ = self.failure(payload)
                self.assertEqual(code, error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_provider_source_title_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][0]["text"] = "Офіційна статистика торгівлі"
        error, _ = self.failure(payload)
        self.assertEqual("source_name_leakage", error.diagnostics["attempts"][0]["validation_codes"][0])

    # Rendering
    def test_percent_and_decimal_comma_render_naturally(self):
        fact = self.catalog.facts[self.fact_ref("claim-april")]
        self.assertEqual("7,8%", render_presentation_fact(fact, FactDisplayVariant.VALUE_WITH_UNIT))

    def test_scaled_currency_renders_naturally(self):
        fact = self.catalog.facts[self.fact_ref("claim-2021")]
        self.assertEqual("близько 1,064 млрд дол. США", render_presentation_fact(fact, FactDisplayVariant.VALUE_WITH_UNIT))

    def test_qualifiers_only_when_authorized(self):
        exact = self.catalog.facts[self.fact_ref("claim-april")]
        approximate = self.catalog.facts[self.fact_ref("claim-2021")]
        greater = self.catalog.facts[self.fact_ref("claim-2025")]
        self.assertFalse(render_presentation_fact(exact, FactDisplayVariant.VALUE_WITH_UNIT).startswith("близько"))
        self.assertTrue(render_presentation_fact(approximate, FactDisplayVariant.VALUE_WITH_UNIT).startswith("близько"))
        self.assertTrue(render_presentation_fact(greater, FactDisplayVariant.VALUE_WITH_UNIT).startswith("понад"))

    def test_period_variants(self):
        self.assertEqual("квітні 2026 року", render_presentation_period("2026-04", PeriodDisplayVariant.LOCATIVE))
        self.assertEqual("січня–квітня 2026 року", render_presentation_period("2026-01/2026-04", PeriodDisplayVariant.GENITIVE_RANGE))
        self.assertEqual("2025 рік", render_presentation_period("2025", PeriodDisplayVariant.NOMINATIVE))

    def test_invalid_period_variant_rejected(self):
        with self.assertRaises(EditorialCompositionError):
            render_presentation_period("2025", PeriodDisplayVariant.GENITIVE_RANGE)

    def test_invalid_fact_variant_rejected(self):
        payload = copy.deepcopy(self.valid); payload["sections"][0]["paragraphs"][0]["segments"][3]["variant"] = "bare_value"
        error, _ = self.failure(payload)
        self.assertEqual("invalid_fact_variant", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_geography_variants(self):
        fact = self.catalog.facts[self.fact_ref("claim-april")]
        self.assertEqual("Україна", render_presentation_geography(fact, GeographyDisplayVariant.NOMINATIVE))
        self.assertEqual("Україні", render_presentation_geography(fact, GeographyDisplayVariant.LOCATIVE))
        self.assertEqual("В Україні", render_presentation_geography(fact, GeographyDisplayVariant.LOCATIVE_WITH_PREPOSITION))

    def test_invalid_geography_variant_rejected(self):
        foreign = replace(self.catalog.facts[self.fact_ref("claim-april")], numeric_fact=replace(self.catalog.facts[self.fact_ref("claim-april")].numeric_fact, geography=("невідома територія",)))
        with self.assertRaises(EditorialCompositionError):
            render_presentation_geography(foreign, GeographyDisplayVariant.LOCATIVE)

    def test_frame_spacing_is_natural(self):
        result, _ = self.compose(self.valid)
        text = result.report.sections[0].paragraphs[0].text
        self.assertIn("квітні 2026 року показник становив 7,8%", text)
        self.assertNotRegex(text, r"[А-Яа-яІіЇїЄєҐґ]\d|\d[А-Яа-яІіЇїЄєҐґ]")

    def test_text_period_text_spacing_is_natural(self):
        result, _ = self.compose(self.valid)
        self.assertIn("У квітні 2026 року показник", result.report.sections[0].paragraphs[0].text)

    def test_citations_are_adjacent_and_deduplicated(self):
        result, _ = self.compose(self.valid)
        paragraph = result.report.sections[0].paragraphs[0]
        self.assertRegex(paragraph.text, r"\[S1\]\.$")
        self.assertEqual(1, paragraph.text.count("[S1]"))

    def test_shared_source_resolves_stably_across_claims(self):
        left = self.catalog.claims["claim-april"].citation_refs[0]
        right = self.catalog.claims["claim-ytd"].citation_refs[0]
        self.assertNotEqual(left, right)
        self.assertEqual("S1", self.catalog.citations[left].display_key)
        self.assertEqual("S1", self.catalog.citations[right].display_key)

    def test_explicit_authorized_citation_is_accepted(self):
        payload = copy.deepcopy(self.valid)
        ref = self.catalog.claims["claim-april"].citation_refs[0]
        payload["sections"][0]["paragraphs"][0]["segments"].append({"type": "CITATION_REF", "claim_ref": "claim-april", "citation_ref": ref})
        result, _ = self.compose(payload)
        self.assertEqual(1, result.report.sections[0].paragraphs[0].text.count("[S1]"))

    def test_cross_claim_citation_borrowing_rejected(self):
        payload = copy.deepcopy(self.valid)
        citation_ref = self.catalog.claims["claim-2021"].citation_refs[0]
        payload["sections"][0]["paragraphs"][0]["segments"].append({"type": "CITATION_REF", "claim_ref": "claim-april", "citation_ref": citation_ref})
        error, _ = self.failure(payload)
        self.assertEqual("cross_claim_citation_ref", error.diagnostics["attempts"][0]["validation_codes"][0])

    # Synthesis
    def test_compatible_two_claim_trend_paragraph(self):
        result, _ = self.compose(self.valid)
        paragraph = result.report.sections[0].paragraphs[0]
        self.assertEqual({"claim-april", "claim-ytd"}, set(paragraph.claim_refs))
        self.assertIn("7,8%", paragraph.text); self.assertIn("8,7%", paragraph.text)

    def test_incompatible_group_is_not_offered(self):
        self.assertFalse(any(set(group.claim_refs) == {"claim-april", "claim-2021"} for group in self.options.groups.values()))

    def test_authorized_interpretation_accepted(self):
        result, _ = self.compose(self.valid)
        self.assertIn("зріс на", result.report.executive_summary.paragraphs[0].text)

    def test_unauthorized_acceleration_rejected(self):
        payload = copy.deepcopy(self.valid)
        payload["executive_summary"][0]["segments"][3]["text"] = "зростання прискорилося"
        error, _ = self.failure(payload)
        self.assertEqual("interpretation_wording_mismatch", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_qualitative_bypass_through_text_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][0]["text"] = "Ринок відновлювався у "
        error, _ = self.failure(payload)
        self.assertEqual("qualitative_bypass", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_claim_facts_remain_claim_scoped(self):
        result, _ = self.compose(self.valid)
        for paragraph in result.report.sections[0].paragraphs:
            for fact_ref in paragraph.fact_refs:
                self.assertIn(self.catalog.facts[fact_ref].claim_ref, paragraph.claim_refs)

    def test_claim_group_does_not_flatten_fact_ownership(self):
        result, _ = self.compose(self.valid)
        paragraph = result.report.sections[0].paragraphs[0]
        ownership = {ref: self.catalog.facts[ref].claim_ref for ref in paragraph.fact_refs}
        self.assertEqual({"claim-april", "claim-ytd"}, set(ownership.values()))

    def test_executive_summary_uses_typed_authority(self):
        result, _ = self.compose(self.valid)
        summary = result.report.executive_summary.paragraphs[0]
        self.assertTrue(summary.fact_refs); self.assertTrue(summary.citation_refs)

    def test_executive_summary_is_not_claim_concatenation(self):
        result, _ = self.compose(self.valid)
        text = " ".join(item.text for item in result.report.executive_summary.paragraphs)
        self.assertNotEqual(" ".join(item.proposition for item in self.claims[:3]), text)

    def test_unsupported_summary_fact_rejected(self):
        payload = copy.deepcopy(self.valid); payload["executive_summary"][0]["segments"][4]["fact_ref"] = "nf-unsupported"
        error, _ = self.failure(payload)
        self.assertEqual("unknown_fact_ref", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_section_contains_multiple_authorized_claims(self):
        result, _ = self.compose(self.valid)
        self.assertEqual({"claim-2021", "claim-2025"}, set(result.report.sections[1].paragraphs[0].claim_refs))

    def test_unsupported_section_rejected(self):
        payload = copy.deepcopy(self.valid)
        payload["sections"].append({"section_id": "empty", "title": "Контекст", "purpose": "Додатковий контекст", "paragraphs": [{"paragraph_id": "empty-p", "group_refs": [], "segments": [{"type": "TEXT", "text": "Загальний огляд"}]}]})
        error, _ = self.failure(payload)
        self.assertEqual("unsupported_section", error.diagnostics["attempts"][0]["validation_codes"][0])

    def test_limitation_is_natural_and_has_no_internal_ids(self):
        text = render_coverage_limitation(self.catalog.limitations["lim-series"])
        self.assertIn("2022–2025 роки", text)
        self.assertNotRegex(text, r"rq|in-|claim-")

    def test_limitation_cannot_invent_missing_period(self):
        request = build_provider_request(catalog=self.catalog, options=self.options, authority_digest="authority")
        self.assertEqual(["2022", "2023", "2024", "2025"], request["limitations"][0]["missing_periods"])
        self.assertNotIn("2021", render_coverage_limitation(self.catalog.limitations["lim-series"]))

    def test_limitation_remains_typed_in_report(self):
        result, _ = self.compose(self.valid)
        self.assertIsInstance(result.report.limitations[0], CoverageLimitation)

    # Repair and call budget
    def test_valid_initial_uses_one_call(self):
        _, provider = self.compose(self.valid)
        self.assertEqual(1, len(provider.requests))

    def test_repairable_initial_uses_exactly_two_calls(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        result, provider = self.compose(invalid, self.valid)
        self.assertEqual(2, len(provider.requests)); self.assertEqual("Огляд роздрібної торгівлі України", result.report.title)

    def test_successful_repair_returns_valid_report(self):
        invalid = copy.deepcopy(self.valid); invalid["sections"][0]["title"] = "Розділ rq1"
        result, _ = self.compose(invalid, self.valid)
        self.assertEqual("desk_editorial_v1", result.report.contract_version)

    def test_invalid_repair_fails_closed_after_two_calls(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        error, provider = self.failure(invalid)
        self.assertEqual(2, len(provider.requests)); self.assertEqual("editorial_composition_failed", error.code)

    def test_no_third_provider_call(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        _, provider = self.failure(invalid)
        self.assertEqual(2, len(provider.requests))

    def test_repair_cannot_mutate_authority(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        original_digest = canonical_catalog_digest(self.catalog)
        self.compose(invalid, self.valid)
        self.assertEqual(original_digest, canonical_catalog_digest(self.catalog))

    def test_repair_diagnostics_identify_initial_failure(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        _, provider = self.compose(invalid, self.valid)
        self.assertEqual(["text_digit_leakage"], provider.requests[1]["repair_diagnostics"]["validation_codes"])

    def test_repair_requests_one_complete_typed_replacement(self):
        invalid = copy.deepcopy(self.valid); invalid["report_title"] = "Огляд 2026"
        _, provider = self.compose(invalid, self.valid)
        self.assertEqual("return one complete corrected desk_editorial_v1 proposal", provider.requests[1]["repair_diagnostics"]["instruction"])

    def test_provider_exception_is_bounded(self):
        error, provider = self.failure(RuntimeError("provider down"), RuntimeError("provider down"))
        self.assertEqual(2, len(provider.requests)); self.assertEqual("provider_failure", error.diagnostics["attempts"][0]["validation_codes"][0])

    # Presentation and golden quality
    def test_presentation_report_quality_contract(self):
        result, provider = self.compose(self.valid)
        report = result.report
        all_text = " ".join([report.title] + [p.text for p in report.executive_summary.paragraphs] + [s.title for s in report.sections] + [p.text for s in report.sections for p in s.paragraphs])
        self.assertTrue(report.title); self.assertEqual(2, len(report.executive_summary.paragraphs)); self.assertEqual(2, len(report.sections))
        self.assertTrue(all(p.citation_refs or p.limitation_refs for p in report.executive_summary.paragraphs))
        self.assertTrue(report.citations); self.assertEqual((self.catalog.limitations["lim-series"],), report.limitations)
        self.assertEqual("authority-digest", report.authority_digest)
        self.assertNotIn("період:", all_text.casefold()); self.assertNotIn("географія:", all_text.casefold())
        self.assertNotRegex(all_text, r"rq\d|[0-9a-f]{8}-[0-9a-f]{4}")
        self.assertIn("7,8%", all_text); self.assertIn("8,7%", all_text)
        self.assertIn("близько 1,064 млрд дол. США", all_text); self.assertIn("понад 7 млрд дол. США", all_text)
        self.assertIn("Україні показник становить 10%", all_text); self.assertIn("Польщі — 20,1%", all_text)
        self.assertIn("Електроніка формує 36%", all_text); self.assertIn("одяг — 23%", all_text)
        self.assertIn("2022–2025 роки", all_text)
        self.assertEqual(1, len(provider.requests))

    def test_reader_facing_titles_are_natural(self):
        result, _ = self.compose(self.valid)
        self.assertTrue(all("rq" not in item.title.casefold() for item in result.report.sections))
        self.assertTrue(all(item.title.strip() for item in result.report.sections))

    def test_reader_facing_output_contains_no_uuid(self):
        result, _ = self.compose(self.valid)
        text = " ".join([result.report.title] + [p.text for p in result.report.executive_summary.paragraphs] + [p.text for s in result.report.sections for p in s.paragraphs])
        self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text, re.I))

    def test_references_include_only_used_authorized_sources(self):
        result, _ = self.compose(self.valid)
        used = {ref for paragraph in result.report.executive_summary.paragraphs for ref in paragraph.citation_refs}
        used.update(ref for section in result.report.sections for paragraph in section.paragraphs for ref in paragraph.citation_refs)
        self.assertEqual(used, {item.citation_ref for item in result.report.citations})
        self.assertTrue(used <= set(self.catalog.citations))

    def test_traceability_retained_per_paragraph(self):
        result, _ = self.compose(self.valid)
        paragraph = result.report.sections[1].paragraphs[0]
        self.assertEqual({"claim-2021", "claim-2025"}, set(paragraph.claim_refs))
        self.assertEqual(2, len(paragraph.fact_refs)); self.assertEqual(2, len(paragraph.period_refs))

    def test_no_h2_proposition_required(self):
        result, _ = self.compose(self.valid)
        all_text = " ".join(p.text for p in result.report.executive_summary.paragraphs)
        self.assertNotIn(self.claims[0].proposition, all_text)

    def test_provider_text_contributes_no_digits(self):
        for section in self.valid["sections"]:
            for paragraph in section["paragraphs"]:
                for segment in paragraph["segments"]:
                    if segment["type"] in {"TEXT", "INTERPRETATION_REF"}:
                        self.assertFalse(any(char.isdigit() for char in segment["text"]))

    def test_deterministic_injection(self):
        first, _ = self.compose(self.valid)
        second, _ = self.compose(self.valid)
        self.assertEqual(first.report, second.report)
        self.assertEqual(first.diagnostics["presentation_digest"], second.diagnostics["presentation_digest"])

    def test_diagnostics_are_bounded_and_structured(self):
        result, _ = self.compose(self.valid)
        expected = {"selected_claim_refs", "selected_fact_refs", "selected_period_refs", "selected_group_refs", "selected_interpretation_refs", "selected_limitation_refs", "resolved_citation_refs", "rendered_fact_expressions", "rendered_period_expressions", "presentation_digest", "provider_call_count"}
        self.assertTrue(expected <= set(result.diagnostics))
        self.assertEqual(1, result.diagnostics["provider_call_count"])

    def test_provider_request_is_bounded_and_excludes_claim_prose(self):
        request = build_provider_request(catalog=self.catalog, options=self.options, authority_digest="authority")
        serialized = repr(request)
        self.assertNotIn("validation representation", serialized)
        self.assertNotIn("canonical_url", serialized)
        self.assertNotIn("Офіційна статистика торгівлі", serialized)

    def test_provider_request_declares_prohibitions(self):
        request = build_provider_request(catalog=self.catalog, options=self.options, authority_digest="authority")
        self.assertEqual(["new_facts", "new_numbers", "new_dates", "new_sources", "new_factual_conclusions"], request["prohibited"])


class LlmEditorialProposalProviderBoundaryTests(EditorialComposerTests):
    class Client:
        def __init__(self, *responses):
            self.responses = list(responses)
            self.calls = 0

        def generate(self, prompt):
            self.calls += 1
            return self.responses.pop(0)

    def response(self, value, *, finish_reason="stop"):
        return LLMResponse(content=value, finish_reason=finish_reason, output_tokens=10, max_output_tokens=4096)

    def test_valid_json_content_reaches_mapping_boundary(self):
        client = self.Client(self.response(json.dumps(self.valid, ensure_ascii=False)))
        payload = LlmEditorialProposalProvider(client).generate({})
        self.assertEqual(self.valid, payload)
        self.assertEqual(1, client.calls)

    def test_invalid_json_fails_closed_with_parse_diagnostic(self):
        client = self.Client(self.response('{"contract_version":'))
        with self.assertRaises(EditorialCompositionError) as raised:
            LlmEditorialProposalProvider(client).generate({})
        self.assertEqual("invalid_json", raised.exception.diagnostics["parse_failure_category"])

    def test_non_object_json_fails_closed(self):
        client = self.Client(self.response("[]"))
        with self.assertRaises(EditorialCompositionError) as raised:
            LlmEditorialProposalProvider(client).generate({})
        self.assertEqual("non_object_root", raised.exception.diagnostics["parse_failure_category"])

    def test_empty_and_truncated_json_fail_closed(self):
        for content in ("", '{"contract_version":"desk_editorial_v1"'):
            client = self.Client(self.response(content))
            with self.assertRaises(EditorialCompositionError):
                LlmEditorialProposalProvider(client).generate({})

    def test_fenced_and_prose_json_remain_rejected_by_syntax_validator(self):
        for content in (f"```json\n{json.dumps(self.valid)}\n```", f"Here is JSON: {json.dumps(self.valid)}"):
            client = self.Client(self.response(content))
            with self.assertRaises(EditorialCompositionError) as raised:
                LlmEditorialProposalProvider(client).generate({})
            self.assertEqual("invalid_json", raised.exception.diagnostics["parse_failure_category"])

    def test_initial_invalid_repair_valid_uses_two_calls(self):
        client = self.Client(self.response("not json"), self.response(json.dumps(self.valid, ensure_ascii=False)))
        result = EditorialComposer(LlmEditorialProposalProvider(client)).compose(
            report_id="report-1", revision_number=1, source_report_id="report-1",
            authority_digest="authority-digest", catalog=self.catalog,
        )
        self.assertEqual("desk_editorial_v1", result.report.contract_version)
        self.assertEqual(2, client.calls)

    def test_initial_and_repair_invalid_are_bounded_to_two_calls(self):
        client = self.Client(self.response("bad"), self.response("still bad"))
        with self.assertRaises(EditorialCompositionError):
            EditorialComposer(LlmEditorialProposalProvider(client)).compose(
                report_id="report-1", revision_number=1, source_report_id="report-1",
                authority_digest="authority-digest", catalog=self.catalog,
            )
        self.assertEqual(2, client.calls)

    def test_valid_initial_uses_one_call(self):
        client = self.Client(self.response(json.dumps(self.valid, ensure_ascii=False)))
        EditorialComposer(LlmEditorialProposalProvider(client)).compose(
            report_id="report-1", revision_number=1, source_report_id="report-1",
            authority_digest="authority-digest", catalog=self.catalog,
        )
        self.assertEqual(1, client.calls)

    def test_decoded_schema_violation_remains_strict(self):
        invalid = copy.deepcopy(self.valid)
        invalid["report_title"] = "Огляд 2026"
        client = self.Client(self.response(json.dumps(invalid)), self.response(json.dumps(invalid)))
        with self.assertRaises(EditorialCompositionError):
            EditorialComposer(LlmEditorialProposalProvider(client)).compose(
                report_id="report-1", revision_number=1, source_report_id="report-1",
                authority_digest="authority-digest", catalog=self.catalog,
            )
        self.assertEqual(2, client.calls)


def canonical_catalog_digest(catalog):
    return (
        tuple(catalog.claims), tuple(catalog.facts), tuple(catalog.periods),
        tuple(catalog.citations), tuple(catalog.limitations),
    )


if __name__ == "__main__":
    unittest.main()
