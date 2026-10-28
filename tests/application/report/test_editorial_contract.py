from __future__ import annotations

from dataclasses import replace
import unittest

from application.report.claim_contract import canonical_digest
from application.report.editorial_contract import (
    EDITORIAL_CONTRACT_VERSION,
    AuthorizedEditorialCatalog,
    ClaimGroupRelation,
    CoverageLimitation,
    CoverageStatus,
    EditorialClaimGroup,
    EditorialContractError,
    EditorialDiagnosticCode,
    EditorialInterpretation,
    EditorialPlan,
    EditorialSectionPlan,
    EditorialUnit,
    EditorialUnitType,
    EvidenceRequirementLabel,
    ImpactLabel,
    InterpretationLabel,
    MissingDimension,
    PresentationExecutiveSummary,
    PresentationReport,
    PresentationSection,
    build_authorized_editorial_catalog,
    deterministic_group_id,
    validate_claim_group,
    validate_editorial_plan,
    validate_interpretation,
    validate_provider_text,
)
from domain.reports.report_claim import ClaimScope, NumericFact, ReportClaim


def numeric(value: str, unit: str, period: str, metric: str = "оборот", geography: str = "україна", scale: str = "absolute") -> NumericFact:
    return NumericFact(value, unit, scale, (geography,), (period,), (metric,), ())


def claim(claim_id: str, fact: NumericFact, *, direction: str = "increase", rq: str = "rq1_trajectory", citation: str = "S1", source: str = "source-1") -> ReportClaim:
    scope = ClaimScope((fact.geography[0],), (), fact.periods, fact.metrics, (), (fact,))
    return ReportClaim(
        claim_id=claim_id, project_id="project-1", source_workflow_run_id="source-run",
        report_workflow_run_id="report-run", design_id="design-1",
        research_question_ids=(rq,), information_need_ids=(f"in-{claim_id}",),
        finding_ids=(f"finding-{claim_id}",), insight_ids=(), evidence_ids=(f"evidence-{claim_id}",),
        kind="trend", proposition="validation representation", certainty="direct", direction=direction,
        scope=scope, support_evidence_ids=(f"evidence-{claim_id}",), source_ids=(source,),
        citation_ids=(citation,), finding_content_digests={f"finding-{claim_id}": "fd"},
        evidence_content_digests={f"evidence-{claim_id}": "ed"}, status="validated",
        contract_version="desk_report_claim_v1", authority_digest="authority", validated_at="2026-01-01T00:00:00Z",
    )


class EditorialContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claims = (
            claim("claim-april", numeric("7.8", "%", "2026-04")),
            claim("claim-ytd", numeric("8.7", "%", "2026-01/2026-04")),
            claim("claim-2021", numeric("1.064", "USD", "2021", "e-commerce", scale="billion"), rq="rq3_channel", citation="S2", source="source-2"),
            claim("claim-2025", numeric("7", "USD", "2025", "e-commerce", scale="billion"), rq="rq3_channel", citation="S3", source="source-3"),
            claim("claim-share", numeric("10", "%", "2025", "e-commerce share"), rq="rq3_channel", citation="S3", source="source-3"),
        )
        self.registry = {
            "S1": {"source_id": "source-1", "title": "Official retail statistics", "canonical_url": "https://example.test/retail"},
            "S2": {"source_id": "source-2", "title": "E-commerce baseline", "canonical_url": "https://example.test/base"},
            "S3": {"source_id": "source-3", "title": "E-commerce forecast", "canonical_url": "https://example.test/forecast"},
        }
        initial = build_authorized_editorial_catalog(self.claims, citation_registry=self.registry)
        limitation = CoverageLimitation(
            "lim-series", "market_trajectory", ("claim-april", "claim-ytd"),
            tuple(initial.claims["claim-april"].period_refs + initial.claims["claim-ytd"].period_refs),
            (MissingDimension.PERIOD,), ("2022", "2023", "2024", "2025"),
            CoverageStatus.INCOMPLETE_SERIES, ImpactLabel.LIMITS_TREND_INFERENCE,
            (EvidenceRequirementLabel.ADDITIONAL_PERIODS,),
        )
        self.catalog = build_authorized_editorial_catalog(self.claims, citation_registry=self.registry, limitations=(limitation,))

    def unit(self, unit_id: str, type_: EditorialUnitType, **kwargs) -> EditorialUnit:
        return EditorialUnit(unit_id, type_, **kwargs)

    def minimal_plan(self) -> EditorialPlan:
        units = (
            self.unit("u-summary", EditorialUnitType.TEXT, text="Ключовий висновок"),
            self.unit("u-text", EditorialUnitType.TEXT, text="Ключова динаміка ринку"),
            self.unit("u-claim", EditorialUnitType.CLAIM_REF, claim_ref="claim-april"),
        )
        return EditorialPlan(
            EDITORIAL_CONTRACT_VERSION, "Огляд роздрібного ринку", ("u-summary",),
            (EditorialSectionPlan("section-market", "Динаміка ринку", "Опис підтриманої динаміки", ("u-text", "u-claim")),),
            units,
        )

    def assert_code(self, code: EditorialDiagnosticCode, function, *args, **kwargs) -> None:
        with self.assertRaises(EditorialContractError) as captured:
            function(*args, **kwargs)
        self.assertEqual(code, captured.exception.code)

    # Contract and discriminator
    def test_valid_minimal_plan(self):
        validate_editorial_plan(self.minimal_plan(), self.catalog)

    def test_wrong_contract_version_rejected(self):
        self.assert_code(EditorialDiagnosticCode.UNSUPPORTED_CONTRACT_VERSION, validate_editorial_plan, replace(self.minimal_plan(), contract_version="wrong"), self.catalog)

    def test_malformed_unit_rejects_irrelevant_field(self):
        self.assert_code(EditorialDiagnosticCode.MALFORMED_UNIT, EditorialUnit, "u", EditorialUnitType.TEXT, text="зв'язок", claim_ref="claim-april")

    def test_malformed_unit_payload_rejected(self):
        self.assert_code(EditorialDiagnosticCode.MALFORMED_UNIT, EditorialUnit.from_dict, {"unit_id": "u", "type": "UNKNOWN"})

    def test_duplicate_unit_ids_rejected(self):
        plan = self.minimal_plan()
        self.assert_code(EditorialDiagnosticCode.DUPLICATE_ID, validate_editorial_plan, replace(plan, units=plan.units + (replace(plan.units[0]),)), self.catalog)

    def test_duplicate_section_ids_rejected(self):
        plan = self.minimal_plan()
        self.assert_code(EditorialDiagnosticCode.DUPLICATE_ID, validate_editorial_plan, replace(plan, sections=plan.sections + (replace(plan.sections[0]),)), self.catalog)

    # TEXT leakage
    def test_connective_ukrainian_text_accepted(self):
        validate_provider_text("Водночас доступні дані вказують на таку динаміку")

    def test_digit_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.TEXT_DIGIT_LEAKAGE, validate_provider_text, "Зростання становило 8 відсотків")

    def test_rq_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Висновок для rq1_trajectory")

    def test_information_need_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Потреба in-market-size")

    def test_finding_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Згідно finding-abc")

    def test_evidence_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Згідно evidence-abc")

    def test_claim_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Твердження claim-april")

    def test_citation_id_leakage_rejected(self):
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_provider_text, "Посилання citation-source")

    def test_raw_url_rejected(self):
        self.assert_code(EditorialDiagnosticCode.URL_LEAKAGE, validate_provider_text, "Джерело https://example.test")

    def test_h2_period_annotation_rejected(self):
        self.assert_code(EditorialDiagnosticCode.H2_ANNOTATION_LEAKAGE, validate_provider_text, "Значення (період: квітень)")

    def test_h2_geography_annotation_rejected(self):
        self.assert_code(EditorialDiagnosticCode.H2_ANNOTATION_LEAKAGE, validate_provider_text, "Значення географія: Україна")

    # Facts, periods, citations
    def test_valid_fact_ref_accepted(self):
        ref = self.catalog.claims["claim-april"].fact_refs[0]
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.FACT_REF, claim_ref="claim-april", fact_ref=ref))
        validate_editorial_plan(plan, self.catalog)

    def test_unknown_fact_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.FACT_REF, claim_ref="claim-april", fact_ref="nf-missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_FACT, validate_editorial_plan, plan, self.catalog)

    def test_unknown_claim_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.CLAIM_REF, claim_ref="claim-missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_CLAIM, validate_editorial_plan, plan, self.catalog)

    def test_wrong_claim_fact_rejected(self):
        ref = self.catalog.claims["claim-april"].fact_refs[0]
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.FACT_REF, claim_ref="claim-ytd", fact_ref=ref))
        self.assert_code(EditorialDiagnosticCode.CROSS_CLAIM_FACT, validate_editorial_plan, plan, self.catalog)

    def test_same_numeric_value_on_different_claim_isolated(self):
        duplicated = replace(self.claims[0], claim_id="claim-other", information_need_ids=("in-other",), finding_ids=("finding-other",), evidence_ids=("evidence-other",), support_evidence_ids=("evidence-other",), finding_content_digests={"finding-other": "fd"}, evidence_content_digests={"evidence-other": "ed"})
        catalog = build_authorized_editorial_catalog((self.claims[0], duplicated), citation_registry=self.registry)
        self.assertNotEqual(catalog.claims["claim-april"].fact_refs, catalog.claims["claim-other"].fact_refs)

    def test_fact_identity_is_stable(self):
        rebuilt = build_authorized_editorial_catalog(self.claims, citation_registry=self.registry)
        self.assertEqual(self.catalog.claims["claim-april"].fact_refs, rebuilt.claims["claim-april"].fact_refs)

    def test_valid_period_ref_accepted(self):
        ref = self.catalog.claims["claim-april"].period_refs[0]
        validate_editorial_plan(self._single_reference_plan(self.unit("u-ref", EditorialUnitType.PERIOD_REF, claim_ref="claim-april", period_ref=ref)), self.catalog)

    def test_unknown_period_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.PERIOD_REF, claim_ref="claim-april", period_ref="ep-missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_PERIOD, validate_editorial_plan, plan, self.catalog)

    def test_cross_claim_period_rejected(self):
        ref = self.catalog.claims["claim-april"].period_refs[0]
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.PERIOD_REF, claim_ref="claim-ytd", period_ref=ref))
        self.assert_code(EditorialDiagnosticCode.CROSS_CLAIM_PERIOD, validate_editorial_plan, plan, self.catalog)

    def test_valid_citation_ref_accepted(self):
        ref = self.catalog.claims["claim-april"].citation_refs[0]
        validate_editorial_plan(self._single_reference_plan(self.unit("u-ref", EditorialUnitType.CITATION_REF, claim_ref="claim-april", citation_ref=ref)), self.catalog)

    def test_unknown_citation_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.CITATION_REF, claim_ref="claim-april", citation_ref="ec-missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_CITATION, validate_editorial_plan, plan, self.catalog)

    def test_cross_claim_citation_rejected(self):
        ref = self.catalog.claims["claim-april"].citation_refs[0]
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.CITATION_REF, claim_ref="claim-ytd", citation_ref=ref))
        self.assert_code(EditorialDiagnosticCode.CROSS_CLAIM_CITATION, validate_editorial_plan, plan, self.catalog)

    def test_shared_source_remains_claim_scoped(self):
        refs = (self.catalog.claims["claim-april"].citation_refs[0], self.catalog.claims["claim-ytd"].citation_refs[0])
        self.assertNotEqual(*refs)
        self.assertEqual({self.catalog.citations[ref].source_id for ref in refs}, {"source-1"})

    # Groups and interpretations
    def test_valid_trend_group(self):
        group = self._group(("claim-april", "claim-ytd"), ClaimGroupRelation.TREND)
        validate_claim_group(group, self.catalog)

    def test_incompatible_metric_group_rejected(self):
        group = self._group(("claim-april", "claim-share"), ClaimGroupRelation.COMPARISON)
        self.assert_code(EditorialDiagnosticCode.INCOMPATIBLE_GROUP, validate_claim_group, group, self.catalog)

    def test_incompatible_geography_group_rejected(self):
        foreign = replace(self.claims[1], claim_id="claim-foreign", scope=replace(self.claims[1].scope, geography_country=("польща",), numeric_facts=(replace(self.claims[1].scope.numeric_facts[0], geography=("польща",)),)), information_need_ids=("in-foreign",), finding_ids=("finding-foreign",), evidence_ids=("evidence-foreign",), support_evidence_ids=("evidence-foreign",), finding_content_digests={"finding-foreign": "fd"}, evidence_content_digests={"evidence-foreign": "ed"})
        catalog = build_authorized_editorial_catalog((self.claims[0], foreign), citation_registry=self.registry)
        group = EditorialClaimGroup(deterministic_group_id(("claim-april", "claim-foreign"), ClaimGroupRelation.COMPARISON), ("claim-april", "claim-foreign"), ClaimGroupRelation.COMPARISON)
        self.assert_code(EditorialDiagnosticCode.INCOMPATIBLE_GROUP, validate_claim_group, group, catalog)

    def test_incompatible_unit_scale_group_rejected(self):
        group = self._group(("claim-april", "claim-2021"), ClaimGroupRelation.COMPARISON)
        self.assert_code(EditorialDiagnosticCode.INCOMPATIBLE_GROUP, validate_claim_group, group, self.catalog)

    def test_same_rq_is_not_automatic_group_authority(self):
        group = self._group(("claim-2021", "claim-share"), ClaimGroupRelation.COMPARISON)
        self.assert_code(EditorialDiagnosticCode.INCOMPATIBLE_GROUP, validate_claim_group, group, self.catalog)

    def test_authorized_increase_interpretation(self):
        validate_interpretation(EditorialInterpretation("i", ("claim-april",), InterpretationLabel.INCREASE, "Показник зростав"), self.catalog)

    def test_authorized_decrease_interpretation(self):
        falling = replace(self.claims[0], direction="decrease")
        catalog = build_authorized_editorial_catalog((falling,), citation_registry=self.registry)
        validate_interpretation(EditorialInterpretation("i", (falling.claim_id,), InterpretationLabel.DECREASE, "Показник знижувався"), catalog)

    def test_acceleration_rejected_when_not_comparable(self):
        item = EditorialInterpretation("i", ("claim-april", "claim-2021"), InterpretationLabel.ACCELERATION, "Динаміка прискорилася")
        self.assert_code(EditorialDiagnosticCode.UNSUPPORTED_INTERPRETATION, validate_interpretation, item, self.catalog)

    def test_unsupported_recovery_rejected(self):
        item = EditorialInterpretation("i", ("claim-april",), InterpretationLabel.RECOVERY, "Ринок відновлювався")
        self.assert_code(EditorialDiagnosticCode.UNSUPPORTED_INTERPRETATION, validate_interpretation, item, self.catalog)

    def test_interpretation_with_unauthorized_claim_rejected(self):
        item = EditorialInterpretation("i", ("claim-missing",), InterpretationLabel.INCREASE, "Показник зростав")
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_CLAIM, validate_interpretation, item, self.catalog)

    def test_digit_in_interpretation_rejected(self):
        self.assert_code(EditorialDiagnosticCode.TEXT_DIGIT_LEAKAGE, EditorialInterpretation, "i", ("claim-april",), InterpretationLabel.INCREASE, "Зростання на 8 відсотків")

    # Limitations and plans
    def test_valid_typed_coverage_limitation(self):
        self.assertIn("lim-series", self.catalog.limitations)

    def test_limitation_has_no_reader_facing_rq_id(self):
        self.assertEqual("market_trajectory", self.catalog.limitations["lim-series"].topic_ref)

    def test_arbitrary_free_limitation_fields_are_unavailable(self):
        self.assert_code(EditorialDiagnosticCode.INVALID_LIMITATION, CoverageLimitation, "lim", "topic", (), (), (), (), CoverageStatus.PARTIAL, ImpactLabel.REQUIRES_CAUTION, ())

    def test_unknown_missing_dimension_rejected_by_enum(self):
        with self.assertRaises(ValueError):
            MissingDimension("invented")

    def test_unsupported_missing_period_ref_rejected(self):
        bad = replace(self.catalog.limitations["lim-series"], limitation_id="bad", supported_period_refs=("ep-missing",))
        self.assert_code(EditorialDiagnosticCode.INVALID_LIMITATION, build_authorized_editorial_catalog, self.claims, citation_registry=self.registry, limitations=(bad,))

    def test_unknown_unit_in_section_rejected(self):
        plan = replace(self.minimal_plan(), sections=(replace(self.minimal_plan().sections[0], unit_ids=("u-missing",)),))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_UNIT, validate_editorial_plan, plan, self.catalog)

    def test_orphan_unit_rejected(self):
        plan = self.minimal_plan()
        orphan = self.unit("u-orphan", EditorialUnitType.TEXT, text="Додатковий перехід")
        self.assert_code(EditorialDiagnosticCode.ORPHAN_UNIT, validate_editorial_plan, replace(plan, units=plan.units + (orphan,)), self.catalog)

    def test_unit_cannot_be_owned_by_summary_and_section(self):
        plan = self.minimal_plan()
        self.assert_code(EditorialDiagnosticCode.DUPLICATE_UNIT_OWNERSHIP, validate_editorial_plan, replace(plan, executive_summary_unit_ids=("u-text",)), self.catalog)

    def test_unknown_claim_group_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.CLAIM_GROUP_REF, claim_group_ref="missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_GROUP, validate_editorial_plan, plan, self.catalog)

    def test_orphan_claim_group_rejected(self):
        plan = self.minimal_plan()
        group = self._group(("claim-april", "claim-ytd"), ClaimGroupRelation.TREND)
        self.assert_code(EditorialDiagnosticCode.ORPHAN_GROUP, validate_editorial_plan, replace(plan, claim_groups=(group,)), self.catalog)

    def test_unknown_interpretation_ref_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.INTERPRETATION_REF, interpretation_ref="missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_INTERPRETATION, validate_editorial_plan, plan, self.catalog)

    def test_unknown_limitation_rejected(self):
        plan = self._single_reference_plan(self.unit("u-ref", EditorialUnitType.LIMITATION_REF, limitation_ref="missing"))
        self.assert_code(EditorialDiagnosticCode.UNKNOWN_LIMITATION, validate_editorial_plan, plan, self.catalog)

    def test_internal_id_in_section_title_rejected(self):
        plan = self.minimal_plan()
        section = replace(plan.sections[0], title="Результати rq1_trajectory")
        self.assert_code(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE, validate_editorial_plan, replace(plan, sections=(section,)), self.catalog)

    def test_digit_in_provider_title_rejected(self):
        self.assert_code(EditorialDiagnosticCode.TEXT_DIGIT_LEAKAGE, validate_editorial_plan, replace(self.minimal_plan(), report_title="Ринок 2026"), self.catalog)

    def test_system_owned_title_may_contain_period(self):
        validate_editorial_plan(replace(self.minimal_plan(), report_title="Ринок у 2021–2026 роках", title_is_system_owned=True), self.catalog)

    def test_missing_executive_unit_rejected(self):
        self.assert_code(EditorialDiagnosticCode.MISSING_EXECUTIVE_UNIT, validate_editorial_plan, replace(self.minimal_plan(), executive_summary_unit_ids=()), self.catalog)

    def test_valid_production_shaped_plan(self):
        group = self._group(("claim-april", "claim-ytd"), ClaimGroupRelation.TREND)
        units = (
            self.unit("u-summary", EditorialUnitType.TEXT, text="Ключова динаміка підтверджена доступними даними"),
            self.unit("u-summary-group", EditorialUnitType.CLAIM_GROUP_REF, claim_group_ref=group.claim_group_id),
            self.unit("u-intro", EditorialUnitType.TEXT, text="Доступні дані показують таку динаміку"),
            self.unit("u-group", EditorialUnitType.CLAIM_GROUP_REF, claim_group_ref=group.claim_group_id),
            self.unit("u-limit", EditorialUnitType.LIMITATION_REF, limitation_ref="lim-series"),
        )
        plan = EditorialPlan(EDITORIAL_CONTRACT_VERSION, "Огляд роздрібного ринку", ("u-summary", "u-summary-group"), (EditorialSectionPlan("trajectory", "Динаміка ринку", "Підтверджена траєкторія та обмеження", ("u-intro", "u-group", "u-limit")),), units, (group,), limitation_refs=("lim-series",))
        validate_editorial_plan(plan, self.catalog)

    # Presentation shell and identity
    def test_presentation_report_constructible(self):
        self._presentation_report()

    def test_presentation_report_retains_authority_identity(self):
        report = self._presentation_report()
        self.assertEqual("authority-digest", report.authority_digest)

    def test_presentation_report_retains_citations(self):
        report = self._presentation_report()
        self.assertEqual(tuple(self.catalog.citations.values()), report.citations)

    def test_presentation_report_retains_limitations(self):
        report = self._presentation_report()
        self.assertEqual((self.catalog.limitations["lim-series"],), report.limitations)

    def test_presentation_report_does_not_require_h2_proposition(self):
        report = self._presentation_report()
        self.assertNotIn("proposition", report.__dataclass_fields__)

    def test_catalog_is_deterministic_for_same_claims(self):
        rebuilt = build_authorized_editorial_catalog(tuple(reversed(self.claims)), citation_registry=self.registry, limitations=tuple(self.catalog.limitations.values()))
        self.assertEqual(tuple(self.catalog.claims), tuple(rebuilt.claims))
        self.assertEqual(tuple(self.catalog.facts), tuple(rebuilt.facts))

    def test_catalog_preserves_lineage(self):
        entry = self.catalog.claims["claim-april"]
        self.assertEqual(("finding-claim-april",), entry.finding_refs)
        self.assertEqual(("evidence-claim-april",), entry.evidence_refs)

    def test_catalog_maps_are_immutable(self):
        with self.assertRaises(TypeError):
            self.catalog.claims["other"] = self.catalog.claims["claim-april"]  # type: ignore[index]

    def test_fact_preserves_all_authority_dimensions(self):
        fact = self.catalog.facts[self.catalog.claims["claim-2021"].fact_refs[0]].numeric_fact
        self.assertEqual(self.claims[2].scope.numeric_facts[0], fact)

    def _single_reference_plan(self, unit: EditorialUnit) -> EditorialPlan:
        summary = self.unit("u-summary", EditorialUnitType.TEXT, text="Ключовий висновок")
        return EditorialPlan(EDITORIAL_CONTRACT_VERSION, "Огляд ринку", (summary.unit_id,), (EditorialSectionPlan("section", "Огляд", "Підтверджений зміст", (unit.unit_id,)),), (summary, unit))

    def _group(self, refs: tuple[str, ...], relation: ClaimGroupRelation) -> EditorialClaimGroup:
        return EditorialClaimGroup(deterministic_group_id(refs, relation), refs, relation)

    def _presentation_report(self) -> PresentationReport:
        return PresentationReport(
            EDITORIAL_CONTRACT_VERSION, "report-1", 1, "source-report-1", "authority-digest",
            "Огляд ринку", PresentationExecutiveSummary(("u-summary",)),
            (PresentationSection("section", "Динаміка ринку", ("u-body",)),),
            (self.catalog.limitations["lim-series"],), tuple(self.catalog.citations.values()),
        )


if __name__ == "__main__":
    unittest.main()
