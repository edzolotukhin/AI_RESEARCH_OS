from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import itertools
import re
from typing import Any, Mapping, Protocol
import json

from domain.ai.prompt import Prompt
from application.structured_output.json_validator import JsonValidator

from application.report.claim_contract import canonical_digest
from application.report.editorial_contract import (
    EDITORIAL_CONTRACT_VERSION,
    AuthorizedEditorialCatalog,
    ClaimGroupRelation,
    CoverageLimitation,
    CoverageStatus,
    EditorialClaimGroup,
    EditorialContractError,
    EditorialInterpretation,
    EditorialPlan,
    EditorialSectionPlan,
    EditorialUnit,
    EditorialUnitType,
    EvidenceRequirementLabel,
    ImpactLabel,
    InterpretationLabel,
    MissingDimension,
    PresentationCitation,
    PresentationExecutiveSummary,
    PresentationFact,
    PresentationParagraph,
    PresentationQualifier,
    PresentationReport,
    PresentationSection,
    deterministic_group_id,
    validate_claim_group,
    validate_editorial_plan,
    validate_interpretation,
    validate_provider_text,
)


class EditorialCompositionError(ValueError):
    def __init__(self, code: str, *, diagnostics: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.diagnostics = dict(diagnostics or {})
        super().__init__(code)


class EditorialProposalProvider(Protocol):
    def generate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class LlmEditorialProposalProvider:
    """Production adapter; the deterministic composer remains the authority boundary."""

    def __init__(self, client) -> None:
        self._client = client
        self.last_diagnostics: dict[str, Any] = {}

    def generate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._client.generate(Prompt(
            system=(
                "Create a Ukrainian desk-research editorial plan using only the supplied "
                "opaque options and references. Return one JSON object only. Never invent "
                "facts, identifiers, citations, periods, or limitations."
            ),
            user=json.dumps(dict(request), ensure_ascii=False, sort_keys=True),
        ))
        result = JsonValidator().validate(response.content or "")
        common = {
            "response_type": type(response).__name__,
            "content_present": bool(response.content),
            "content_length": len(response.content or ""),
            "finish_reason": response.finish_reason,
            "incomplete_reason": response.incomplete_reason,
        }
        self.last_diagnostics = dict(common)
        if not result.is_valid:
            raise EditorialCompositionError(
                "malformed_editorial_provider_payload",
                diagnostics={
                    **common,
                    "parse_failure_category": "invalid_json",
                    "error_position": result.error_position,
                },
            )
        payload = result.data
        self.last_diagnostics["decoded_root_type"] = type(payload).__name__
        if not isinstance(payload, Mapping):
            raise EditorialCompositionError(
                "malformed_editorial_provider_payload",
                diagnostics={
                    **common,
                    "parse_failure_category": "non_object_root",
                    "decoded_root_type": type(payload).__name__,
                },
            )
        return payload


class FrameSegmentType(str, Enum):
    TEXT = "TEXT"
    FACT_REF = "FACT_REF"
    PERIOD_REF = "PERIOD_REF"
    GEOGRAPHY_REF = "GEOGRAPHY_REF"
    METRIC_REF = "METRIC_REF"
    POPULATION_REF = "POPULATION_REF"
    CITATION_REF = "CITATION_REF"
    INTERPRETATION_REF = "INTERPRETATION_REF"
    LIMITATION_REF = "LIMITATION_REF"


class FactDisplayVariant(str, Enum):
    VALUE_WITH_UNIT = "value_with_unit"


class PeriodDisplayVariant(str, Enum):
    NOMINATIVE = "nominative"
    LOCATIVE = "locative"
    GENITIVE_RANGE = "genitive_range"


class GeographyDisplayVariant(str, Enum):
    NOMINATIVE = "nominative"
    LOCATIVE = "locative"
    LOCATIVE_WITH_PREPOSITION = "locative_with_preposition"


class PopulationDisplayVariant(str, Enum):
    NOMINATIVE = "nominative"
    SENTENCE_START = "sentence_start"


@dataclass(frozen=True)
class EditorialFrameSegment:
    type: FrameSegmentType
    text: str | None = None
    claim_ref: str | None = None
    fact_ref: str | None = None
    period_ref: str | None = None
    citation_ref: str | None = None
    interpretation_ref: str | None = None
    limitation_ref: str | None = None
    variant: str | None = None


@dataclass(frozen=True)
class EditorialParagraphProposal:
    paragraph_id: str
    group_refs: tuple[str, ...]
    segments: tuple[EditorialFrameSegment, ...]


@dataclass(frozen=True)
class EditorialSectionProposal:
    section_id: str
    title: str
    purpose: str
    paragraphs: tuple[EditorialParagraphProposal, ...]


@dataclass(frozen=True)
class EditorialProposal:
    contract_version: str
    report_title: str
    executive_summary: tuple[EditorialParagraphProposal, ...]
    sections: tuple[EditorialSectionProposal, ...]


@dataclass(frozen=True)
class EditorialOptionCatalog:
    groups: Mapping[str, EditorialClaimGroup]
    interpretations: Mapping[str, tuple[tuple[str, ...], InterpretationLabel]]


@dataclass(frozen=True)
class EditorialCompositionResult:
    report: PresentationReport
    plan: EditorialPlan
    diagnostics: Mapping[str, Any]


_MONTHS_NOMINATIVE = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
_MONTHS_LOCATIVE = {
    1: "січні", 2: "лютому", 3: "березні", 4: "квітні", 5: "травні", 6: "червні",
    7: "липні", 8: "серпні", 9: "вересні", 10: "жовтні", 11: "листопаді", 12: "грудні",
}
_MONTHS_GENITIVE = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}
_UNIT_LABELS = {"USD": "дол. США", "UAH": "грн", "грн": "грн"}
_SCALE_LABELS = {"million": "млн", "billion": "млрд", "thousand": "тис."}
_GEO_LOCATIVE = {"україна": "Україні", "київ": "Києві", "польща": "Польщі"}
_QUALITATIVE_STEMS = (
    "прискор", "уповільн", "віднов", "зрост", "збільш", "скороч", "зниж", "падін",
    "стабіл", "вищ", "нижч", "перевищ", "контраст", "нерівномір", "зріс",
    "прогноз", "оцін", "приблиз", "близько", "понад", "менше ніж",
)
_LABEL_STEMS = {
    InterpretationLabel.RECOVERY: ("віднов",),
    InterpretationLabel.ACCELERATION: ("прискор",),
    InterpretationLabel.DECLINE: ("скороч", "зниж", "падін"),
    InterpretationLabel.INCREASE: ("зрост", "збільш", "зріс"),
    InterpretationLabel.DECREASE: ("скороч", "зниж", "падін"),
    InterpretationLabel.CONTRAST: ("контраст", "вищ", "нижч", "перевищ", "відрізн"),
    InterpretationLabel.STABLE: ("стабіл", "незмін"),
    InterpretationLabel.MIXED: ("змішан", "нерівномір"),
}


class EditorialComposer:
    def __init__(self, provider: EditorialProposalProvider) -> None:
        self._provider = provider

    def compose(
        self, *, report_id: str, revision_number: int, source_report_id: str,
        authority_digest: str, catalog: AuthorizedEditorialCatalog,
        revision_context: Mapping[str, Any] | None = None,
    ) -> EditorialCompositionResult:
        options = build_editorial_options(catalog)
        base_request = build_provider_request(catalog=catalog, options=options, authority_digest=authority_digest)
        if revision_context is not None:
            base_request["revision"] = _bounded_revision_context(revision_context)
        diagnostics: dict[str, Any] = {
            "stage": "editorial_composition", "contract_version": EDITORIAL_CONTRACT_VERSION,
            "provider_call_count": 0, "attempts": [],
        }
        last_error: Exception | None = None
        for attempt in ("initial", "repair"):
            request = dict(base_request)
            request["attempt"] = attempt
            if attempt == "repair":
                request["repair_diagnostics"] = _bounded_error(last_error)
            diagnostics["provider_call_count"] += 1
            try:
                payload = self._provider.generate(request)
                proposal = parse_editorial_proposal(payload)
                result = _resolve_proposal(
                    proposal=proposal, catalog=catalog, options=options, report_id=report_id,
                    revision_number=revision_number, source_report_id=source_report_id,
                    authority_digest=authority_digest, diagnostics=diagnostics,
                )
                attempt_diagnostics = {
                    "attempt": attempt, "status": "valid", "validation_codes": [],
                }
                attempt_diagnostics.update(_safe_adapter_diagnostics(self._provider))
                diagnostics["attempts"].append(attempt_diagnostics)
                diagnostics["presentation_digest"] = canonical_digest(_presentation_digest_payload(result.report))
                diagnostics["stage"] = "editorial_composition_complete"
                return EditorialCompositionResult(result.report, result.plan, diagnostics)
            except Exception as exc:
                last_error = exc
                attempt_diagnostics = {
                    "attempt": attempt, "status": "invalid",
                    "validation_codes": [_error_code(exc)],
                }
                attempt_diagnostics.update(_safe_adapter_diagnostics(self._provider))
                attempt_diagnostics.update(_safe_provider_diagnostics(exc))
                diagnostics["attempts"].append(attempt_diagnostics)
                if attempt == "repair":
                    break
        diagnostics["stage"] = "editorial_composition_failed"
        raise EditorialCompositionError("editorial_composition_failed", diagnostics=diagnostics) from last_error


@dataclass(frozen=True)
class _ResolvedProposal:
    report: PresentationReport
    plan: EditorialPlan


def build_editorial_options(catalog: AuthorizedEditorialCatalog) -> EditorialOptionCatalog:
    groups: dict[str, EditorialClaimGroup] = {}
    claim_refs = tuple(sorted(catalog.claims))
    for left, right in itertools.combinations(claim_refs, 2):
        for relation in ClaimGroupRelation:
            refs = (left, right)
            group = EditorialClaimGroup(deterministic_group_id(refs, relation), refs, relation)
            try:
                validate_claim_group(group, catalog)
            except EditorialContractError:
                continue
            groups[group.claim_group_id] = group
    interpretations: dict[str, tuple[tuple[str, ...], InterpretationLabel]] = {}
    for claim_ref, claim in catalog.claims.items():
        for label in claim.compatible_interpretation_labels:
            ref = _interpretation_ref((claim_ref,), label)
            interpretations[ref] = ((claim_ref,), label)
    for group in groups.values():
        labels = (InterpretationLabel.CONTRAST,) if group.relation == ClaimGroupRelation.CONTRAST else ()
        if group.relation == ClaimGroupRelation.TREND:
            labels += (InterpretationLabel.ACCELERATION,)
        for label in labels:
            item = EditorialInterpretation(_interpretation_ref(group.claim_refs, label), group.claim_refs, label, _default_interpretation_text(label))
            try:
                validate_interpretation(item, catalog)
            except EditorialContractError:
                continue
            interpretations[item.interpretation_id] = (item.claim_refs, label)
    return EditorialOptionCatalog(groups, interpretations)


def build_provider_request(*, catalog: AuthorizedEditorialCatalog, options: EditorialOptionCatalog, authority_digest: str) -> dict[str, Any]:
    return {
        "contract_version": EDITORIAL_CONTRACT_VERSION,
        "role": "organize_phrase_connect_select_only",
        "prohibited": ["new_facts", "new_numbers", "new_dates", "new_sources", "new_factual_conclusions"],
        "authority_digest": authority_digest,
        "claims": [
            {
                "claim_ref": item.claim_ref, "fact_refs": list(item.fact_refs),
                "period_refs": list(item.period_refs), "citation_refs": list(item.citation_refs),
            } for item in catalog.claims.values()
        ],
        "facts": [
            {"fact_ref": item.fact_ref, "claim_ref": item.claim_ref, "fact": item.numeric_fact.to_dict(), "qualifier": item.qualifier.value}
            for item in catalog.facts.values()
        ],
        "periods": [
            {"period_ref": item.period_ref, "claim_ref": item.claim_ref, "fact_ref": item.fact_ref, "period": item.period}
            for item in catalog.periods.values()
        ],
        "citations": [
            {"citation_ref": item.citation_ref, "claim_ref": item.claim_ref, "display_key": item.display_key}
            for item in catalog.citations.values()
        ],
        "groups": [
            {"claim_group_ref": item.claim_group_id, "claim_refs": list(item.claim_refs), "relation": item.relation.value}
            for item in options.groups.values()
        ],
        "interpretations": [
            {"interpretation_ref": ref, "claim_refs": list(value[0]), "label": value[1].value}
            for ref, value in options.interpretations.items()
        ],
        "limitations": [
            {
                "limitation_ref": item.limitation_id, "topic_ref": item.topic_ref,
                "missing_dimensions": [value.value for value in item.missing_dimensions],
                "missing_periods": list(item.missing_periods), "coverage_status": item.coverage_status.value,
                "impact_label": item.impact_label.value,
            } for item in catalog.limitations.values()
        ],
        "response_schema": {
            "fields": ["contract_version", "report_title", "executive_summary", "sections"],
            "frame_segment_types": [item.value for item in FrameSegmentType],
        },
    }


def _bounded_revision_context(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"previous_presentation", "issues", "allowed_targets"}
    if set(value) != allowed:
        raise EditorialCompositionError("revision_context_schema")
    previous = value["previous_presentation"]
    issues = value["issues"]
    targets = value["allowed_targets"]
    if not isinstance(previous, Mapping) or not isinstance(issues, list) or not isinstance(targets, list):
        raise EditorialCompositionError("revision_context_schema")
    if len(issues) > 32 or len(targets) > 128:
        raise EditorialCompositionError("revision_context_bounds")
    bounded_issues = []
    for item in issues:
        if not isinstance(item, Mapping) or set(item) != {"target_type", "target_ref", "issue_type", "revision_instruction"}:
            raise EditorialCompositionError("revision_context_schema")
        bounded_issues.append({key: str(item[key])[:500] for key in item})
    bounded_targets = []
    for item in targets:
        if not isinstance(item, Mapping) or set(item) != {"target_type", "target_ref"}:
            raise EditorialCompositionError("revision_context_schema")
        bounded_targets.append({key: str(item[key])[:128] for key in item})
    return {
        "previous_presentation": dict(previous),
        "issues": bounded_issues,
        "allowed_targets": bounded_targets,
        "mutable": ["wording", "paragraph_order", "section_order", "interpretation_selection", "citation_placement", "limitation_presentation"],
        "prohibited": ["factual_authority", "numeric_facts", "scope", "lineage", "support"],
    }


def parse_editorial_proposal(payload: Mapping[str, Any]) -> EditorialProposal:
    _exact(payload, {"contract_version", "report_title", "executive_summary", "sections"}, "proposal_schema")
    if payload.get("contract_version") != EDITORIAL_CONTRACT_VERSION:
        raise EditorialCompositionError("unsupported_contract_version")
    if not isinstance(payload.get("report_title"), str) or not isinstance(payload.get("executive_summary"), list) or not isinstance(payload.get("sections"), list):
        raise EditorialCompositionError("proposal_schema")
    summary = tuple(_parse_paragraph(item) for item in payload["executive_summary"])
    sections = tuple(_parse_section(item) for item in payload["sections"])
    if not summary or not sections:
        raise EditorialCompositionError("proposal_structure")
    return EditorialProposal(EDITORIAL_CONTRACT_VERSION, payload["report_title"], summary, sections)


def _parse_section(payload: Any) -> EditorialSectionProposal:
    _exact(payload, {"section_id", "title", "purpose", "paragraphs"}, "section_schema")
    if not all(isinstance(payload.get(field), str) for field in ("section_id", "title", "purpose")) or not isinstance(payload.get("paragraphs"), list) or not payload["paragraphs"]:
        raise EditorialCompositionError("section_schema")
    return EditorialSectionProposal(payload["section_id"], payload["title"], payload["purpose"], tuple(_parse_paragraph(item) for item in payload["paragraphs"]))


def _parse_paragraph(payload: Any) -> EditorialParagraphProposal:
    _exact(payload, {"paragraph_id", "group_refs", "segments"}, "paragraph_schema")
    if not isinstance(payload.get("paragraph_id"), str) or not isinstance(payload.get("group_refs"), list) or not isinstance(payload.get("segments"), list) or not payload["segments"]:
        raise EditorialCompositionError("paragraph_schema")
    return EditorialParagraphProposal(payload["paragraph_id"], tuple(_string_list(payload["group_refs"], "paragraph_schema")), tuple(_parse_segment(item) for item in payload["segments"]))


def _parse_segment(payload: Any) -> EditorialFrameSegment:
    if not isinstance(payload, Mapping) or "type" not in payload:
        raise EditorialCompositionError("segment_schema")
    try:
        kind = FrameSegmentType(str(payload["type"]))
    except ValueError as exc:
        raise EditorialCompositionError("segment_schema") from exc
    fields = {
        FrameSegmentType.TEXT: {"type", "text"},
        FrameSegmentType.FACT_REF: {"type", "claim_ref", "fact_ref", "variant"},
        FrameSegmentType.PERIOD_REF: {"type", "claim_ref", "period_ref", "variant"},
        FrameSegmentType.GEOGRAPHY_REF: {"type", "claim_ref", "fact_ref", "variant"},
        FrameSegmentType.METRIC_REF: {"type", "claim_ref", "fact_ref"},
        FrameSegmentType.POPULATION_REF: {"type", "claim_ref", "fact_ref", "variant"},
        FrameSegmentType.CITATION_REF: {"type", "claim_ref", "citation_ref"},
        FrameSegmentType.INTERPRETATION_REF: {"type", "interpretation_ref", "text"},
        FrameSegmentType.LIMITATION_REF: {"type", "limitation_ref"},
    }[kind]
    _exact(payload, fields, "segment_schema")
    values = {key: payload.get(key) for key in fields - {"type"}}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise EditorialCompositionError("segment_schema")
    return EditorialFrameSegment(kind, **values)


def _resolve_proposal(
    *, proposal: EditorialProposal, catalog: AuthorizedEditorialCatalog, options: EditorialOptionCatalog,
    report_id: str, revision_number: int, source_report_id: str, authority_digest: str,
    diagnostics: dict[str, Any],
) -> _ResolvedProposal:
    _validate_editorial_language(proposal.report_title, catalog)
    all_paragraphs = proposal.executive_summary + tuple(paragraph for section in proposal.sections for paragraph in section.paragraphs)
    if len({item.paragraph_id for item in all_paragraphs}) != len(all_paragraphs):
        raise EditorialCompositionError("duplicate_paragraph_id")
    units: list[EditorialUnit] = []
    interpretations: dict[str, EditorialInterpretation] = {}
    used_groups: dict[str, EditorialClaimGroup] = {}
    rendered: dict[str, PresentationParagraph] = {}
    for paragraph in all_paragraphs:
        for group_ref in paragraph.group_refs:
            if group_ref not in options.groups:
                raise EditorialCompositionError("unknown_claim_group")
            used_groups[group_ref] = options.groups[group_ref]
        presentation, paragraph_units, paragraph_interpretations = _render_paragraph(paragraph, catalog, options)
        rendered[paragraph.paragraph_id] = presentation
        units.extend(paragraph_units)
        interpretations.update({item.interpretation_id: item for item in paragraph_interpretations})
    summary_unit_ids = tuple(unit_id for paragraph in proposal.executive_summary for unit_id in rendered[paragraph.paragraph_id].unit_ids)
    sections: list[EditorialSectionPlan] = []
    presentation_sections: list[PresentationSection] = []
    for section in proposal.sections:
        _validate_editorial_language(section.title, catalog)
        _validate_editorial_language(section.purpose, catalog)
        unit_ids = tuple(unit_id for paragraph in section.paragraphs for unit_id in rendered[paragraph.paragraph_id].unit_ids)
        if not any(_paragraph_has_supported_content(rendered[item.paragraph_id]) for item in section.paragraphs):
            raise EditorialCompositionError("unsupported_section")
        sections.append(EditorialSectionPlan(section.section_id, section.title, section.purpose, unit_ids))
        presentation_sections.append(PresentationSection(section.section_id, section.title, unit_ids, tuple(rendered[item.paragraph_id] for item in section.paragraphs)))
    if not any(_paragraph_has_supported_content(rendered[item.paragraph_id]) for item in proposal.executive_summary):
        raise EditorialCompositionError("unsupported_executive_summary")
    limitation_refs = tuple(sorted({ref for paragraph in rendered.values() for ref in paragraph.limitation_refs}))
    plan = EditorialPlan(
        EDITORIAL_CONTRACT_VERSION, proposal.report_title, summary_unit_ids, tuple(sections), tuple(units),
        tuple(used_groups.values()), tuple(interpretations.values()), limitation_refs,
    )
    validate_editorial_plan(plan, catalog)
    used_citations = tuple(sorted({ref for paragraph in rendered.values() for ref in paragraph.citation_refs}))
    report = PresentationReport(
        EDITORIAL_CONTRACT_VERSION, report_id, revision_number, source_report_id, authority_digest,
        proposal.report_title,
        PresentationExecutiveSummary(summary_unit_ids, tuple(rendered[item.paragraph_id] for item in proposal.executive_summary)),
        tuple(presentation_sections), tuple(catalog.limitations[ref] for ref in limitation_refs),
        tuple(catalog.citations[ref] for ref in used_citations),
    )
    _validate_presentation_report(report, authority_digest, catalog)
    diagnostics.update(_selection_diagnostics(plan, report))
    return _ResolvedProposal(report, plan)


def _render_paragraph(
    paragraph: EditorialParagraphProposal, catalog: AuthorizedEditorialCatalog, options: EditorialOptionCatalog,
) -> tuple[PresentationParagraph, tuple[EditorialUnit, ...], tuple[EditorialInterpretation, ...]]:
    rendered: list[str] = []
    units: list[EditorialUnit] = []
    interpretations: list[EditorialInterpretation] = []
    claim_refs: set[str] = set()
    fact_refs: set[str] = set()
    period_refs: set[str] = set()
    explicit_citations: set[str] = set()
    limitation_refs: set[str] = set()
    for index, segment in enumerate(paragraph.segments):
        unit_id = f"eu_{canonical_digest({'paragraph_id': paragraph.paragraph_id, 'index': index, 'segment': segment.__dict__})}"
        if segment.type == FrameSegmentType.TEXT:
            _validate_editorial_language(segment.text or "", catalog)
            value = segment.text or ""
            unit = EditorialUnit(unit_id, EditorialUnitType.TEXT, text=value)
        elif segment.type == FrameSegmentType.FACT_REF:
            fact = _owned_fact(segment.claim_ref, segment.fact_ref, catalog)
            value = render_presentation_fact(fact, _variant(FactDisplayVariant, segment.variant, "invalid_fact_variant"))
            claim_refs.add(fact.claim_ref); fact_refs.add(fact.fact_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.FACT_REF, claim_ref=fact.claim_ref, fact_ref=fact.fact_ref)
        elif segment.type == FrameSegmentType.PERIOD_REF:
            period = _owned_period(segment.claim_ref, segment.period_ref, catalog)
            value = render_presentation_period(period.period, _variant(PeriodDisplayVariant, segment.variant, "invalid_period_variant"))
            claim_refs.add(period.claim_ref); period_refs.add(period.period_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.PERIOD_REF, claim_ref=period.claim_ref, period_ref=period.period_ref)
        elif segment.type == FrameSegmentType.GEOGRAPHY_REF:
            fact = _owned_fact(segment.claim_ref, segment.fact_ref, catalog)
            value = render_presentation_geography(fact, _variant(GeographyDisplayVariant, segment.variant, "invalid_geography_variant"))
            claim_refs.add(fact.claim_ref); fact_refs.add(fact.fact_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.FACT_REF, claim_ref=fact.claim_ref, fact_ref=fact.fact_ref)
        elif segment.type == FrameSegmentType.METRIC_REF:
            fact = _owned_fact(segment.claim_ref, segment.fact_ref, catalog)
            value = render_presentation_metric(fact)
            claim_refs.add(fact.claim_ref); fact_refs.add(fact.fact_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.FACT_REF, claim_ref=fact.claim_ref, fact_ref=fact.fact_ref)
        elif segment.type == FrameSegmentType.POPULATION_REF:
            fact = _owned_fact(segment.claim_ref, segment.fact_ref, catalog)
            value = render_presentation_population(fact, _variant(PopulationDisplayVariant, segment.variant, "invalid_population_variant"))
            claim_refs.add(fact.claim_ref); fact_refs.add(fact.fact_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.FACT_REF, claim_ref=fact.claim_ref, fact_ref=fact.fact_ref)
        elif segment.type == FrameSegmentType.CITATION_REF:
            citation = _owned_citation(segment.claim_ref, segment.citation_ref, catalog)
            value = ""
            claim_refs.add(citation.claim_ref); explicit_citations.add(citation.citation_ref)
            unit = EditorialUnit(unit_id, EditorialUnitType.CITATION_REF, claim_ref=citation.claim_ref, citation_ref=citation.citation_ref)
        elif segment.type == FrameSegmentType.INTERPRETATION_REF:
            option = options.interpretations.get(segment.interpretation_ref or "")
            if option is None:
                raise EditorialCompositionError("unknown_interpretation")
            item = EditorialInterpretation(segment.interpretation_ref or "", option[0], option[1], segment.text or "")
            validate_interpretation(item, catalog)
            _validate_interpretation_wording(item)
            interpretations.append(item); claim_refs.update(item.claim_refs)
            value = item.provider_text
            unit = EditorialUnit(unit_id, EditorialUnitType.INTERPRETATION_REF, interpretation_ref=item.interpretation_id)
        else:
            limitation = catalog.limitations.get(segment.limitation_ref or "")
            if limitation is None:
                raise EditorialCompositionError("unknown_limitation")
            value = render_coverage_limitation(limitation)
            claim_refs.update(limitation.supported_claim_refs); limitation_refs.add(limitation.limitation_id)
            unit = EditorialUnit(unit_id, EditorialUnitType.LIMITATION_REF, limitation_ref=limitation.limitation_id)
        rendered.append(value)
        units.append(unit)
    for group_ref in paragraph.group_refs:
        group = options.groups[group_ref]
        claim_refs.update(group.claim_refs)
        unit_id = f"eu_{canonical_digest({'paragraph_id': paragraph.paragraph_id, 'group_ref': group_ref})}"
        units.append(EditorialUnit(unit_id, EditorialUnitType.CLAIM_GROUP_REF, claim_group_ref=group_ref))
    factual = bool(fact_refs or period_refs or interpretations or paragraph.group_refs)
    citation_refs = set(explicit_citations)
    if factual:
        for claim_ref in claim_refs:
            citation_refs.update(catalog.claims[claim_ref].citation_refs)
        if not citation_refs:
            raise EditorialCompositionError("missing_authorized_citation")
    text = _join_frame(rendered)
    if citation_refs:
        text = _append_citation_markers(text, tuple(sorted(citation_refs)), catalog)
    if not text.strip():
        raise EditorialCompositionError("empty_paragraph")
    paragraph_result = PresentationParagraph(
        paragraph.paragraph_id, text, tuple(item.unit_id for item in units), tuple(sorted(claim_refs)),
        tuple(sorted(fact_refs)), tuple(sorted(period_refs)), tuple(sorted(citation_refs)), tuple(sorted(limitation_refs)),
    )
    return paragraph_result, tuple(units), tuple(interpretations)


def render_presentation_fact(fact: PresentationFact, variant: FactDisplayVariant) -> str:
    if variant != FactDisplayVariant.VALUE_WITH_UNIT:
        raise EditorialCompositionError("invalid_fact_variant")
    numeric = fact.numeric_fact
    value = _display_decimal(numeric.value)
    if numeric.unit == "%":
        rendered = f"{value}%"
    else:
        unit = _UNIT_LABELS.get(numeric.unit, numeric.unit)
        scale = "" if numeric.scale.casefold() in {"", "absolute"} else _SCALE_LABELS.get(numeric.scale.casefold(), numeric.scale)
        rendered = " ".join(item for item in (value, scale, unit) if item)
    prefix = {
        PresentationQualifier.EXACT: "", PresentationQualifier.APPROXIMATE: "близько ",
        PresentationQualifier.GREATER_THAN: "понад ", PresentationQualifier.LESS_THAN: "менше ніж ",
    }[fact.qualifier]
    return prefix + rendered


def render_presentation_period(period: str, variant: PeriodDisplayVariant) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        names = _MONTHS_LOCATIVE if variant == PeriodDisplayVariant.LOCATIVE else _MONTHS_NOMINATIVE
        if variant == PeriodDisplayVariant.GENITIVE_RANGE:
            names = _MONTHS_GENITIVE
        if month not in names:
            raise EditorialCompositionError("invalid_period_value")
        return f"{names[month]} {year} року"
    range_match = re.fullmatch(r"(\d{4})-(\d{2})/(\d{4})-(\d{2})", period)
    if range_match:
        start_year, start_month, end_year, end_month = map(int, range_match.groups())
        if start_year != end_year:
            raise EditorialCompositionError("unsupported_period_display")
        if variant == PeriodDisplayVariant.LOCATIVE:
            names = _MONTHS_LOCATIVE
        elif variant == PeriodDisplayVariant.GENITIVE_RANGE:
            names = _MONTHS_GENITIVE
        else:
            names = _MONTHS_NOMINATIVE
        return f"{names[start_month]}–{names[end_month]} {start_year} року"
    if re.fullmatch(r"\d{4}", period):
        if variant == PeriodDisplayVariant.GENITIVE_RANGE:
            raise EditorialCompositionError("invalid_period_variant")
        return f"{period} році" if variant == PeriodDisplayVariant.LOCATIVE else f"{period} рік"
    raise EditorialCompositionError("unsupported_period_display")


def render_presentation_geography(fact: PresentationFact, variant: GeographyDisplayVariant) -> str:
    values = fact.numeric_fact.geography
    if len(values) != 1:
        raise EditorialCompositionError("unsupported_geography_display")
    value = values[0].strip().casefold()
    if variant == GeographyDisplayVariant.LOCATIVE:
        if value not in _GEO_LOCATIVE:
            raise EditorialCompositionError("invalid_geography_variant")
        return _GEO_LOCATIVE[value]
    if variant == GeographyDisplayVariant.LOCATIVE_WITH_PREPOSITION:
        if value not in _GEO_LOCATIVE:
            raise EditorialCompositionError("invalid_geography_variant")
        return ("В " if value == "україна" else "У ") + _GEO_LOCATIVE[value]
    return values[0].strip().capitalize()


def render_presentation_metric(fact: PresentationFact) -> str:
    metrics = fact.numeric_fact.metrics
    if len(metrics) != 1:
        raise EditorialCompositionError("unsupported_metric_display")
    return metrics[0]


def render_presentation_population(fact: PresentationFact, variant: PopulationDisplayVariant) -> str:
    values = fact.numeric_fact.population_dimensions
    if len(values) != 1:
        raise EditorialCompositionError("unsupported_population_display")
    return values[0].capitalize() if variant == PopulationDisplayVariant.SENTENCE_START else values[0]


def render_coverage_limitation(item: CoverageLimitation) -> str:
    subject = {
        CoverageStatus.INCOMPLETE_SERIES: "Доступні матеріали не формують повного зіставного ряду",
        CoverageStatus.PARTIAL: "Доступні матеріали забезпечують лише часткове покриття",
        CoverageStatus.UNSUPPORTED: "Доступні матеріали не дають достатньої підтримки",
    }[item.coverage_status]
    if item.missing_periods:
        period_text = _missing_period_display(item.missing_periods)
        subject += f" за {period_text}"
    impact = {
        ImpactLabel.LIMITS_COMPARABILITY: "що обмежує пряме зіставлення показників",
        ImpactLabel.LIMITS_TREND_INFERENCE: "тому довгострокову динаміку слід трактувати обережно",
        ImpactLabel.LIMITS_GENERALIZATION: "тому висновки не слід поширювати на непокриті сегменти",
        ImpactLabel.REQUIRES_CAUTION: "тому результати слід трактувати обережно",
    }[item.impact_label]
    return f"{subject}, {impact}."


def _validate_editorial_language(text: str, catalog: AuthorizedEditorialCatalog) -> None:
    try:
        validate_provider_text(text, known_ids=catalog.known_ids)
    except EditorialContractError as exc:
        raise EditorialCompositionError(exc.code.value) from exc
    folded = text.casefold()
    if any(item.title.strip() and item.title.casefold() in folded for item in catalog.citations.values()):
        raise EditorialCompositionError("source_name_leakage")
    if any(stem in folded for stem in _QUALITATIVE_STEMS):
        raise EditorialCompositionError("qualitative_bypass")


def _validate_interpretation_wording(item: EditorialInterpretation) -> None:
    folded = item.provider_text.casefold()
    if not any(stem in folded for stem in _LABEL_STEMS[item.interpretation_label]):
        raise EditorialCompositionError("interpretation_wording_mismatch")
    conflicting = set(_QUALITATIVE_STEMS) - set(_LABEL_STEMS[item.interpretation_label])
    if any(stem in folded for stem in conflicting):
        raise EditorialCompositionError("interpretation_wording_mismatch")


def _owned_fact(claim_ref: str | None, fact_ref: str | None, catalog: AuthorizedEditorialCatalog) -> PresentationFact:
    if claim_ref not in catalog.claims:
        raise EditorialCompositionError("unknown_claim_ref")
    fact = catalog.facts.get(fact_ref or "")
    if fact is None:
        raise EditorialCompositionError("unknown_fact_ref")
    if fact.claim_ref != claim_ref:
        raise EditorialCompositionError("cross_claim_fact_ref")
    return fact


def _variant(enum_type, value: str | None, code: str):
    try:
        return enum_type(value or "")
    except ValueError as exc:
        raise EditorialCompositionError(code) from exc


def _owned_period(claim_ref: str | None, period_ref: str | None, catalog: AuthorizedEditorialCatalog):
    if claim_ref not in catalog.claims:
        raise EditorialCompositionError("unknown_claim_ref")
    period = catalog.periods.get(period_ref or "")
    if period is None:
        raise EditorialCompositionError("unknown_period_ref")
    if period.claim_ref != claim_ref:
        raise EditorialCompositionError("cross_claim_period_ref")
    return period


def _owned_citation(claim_ref: str | None, citation_ref: str | None, catalog: AuthorizedEditorialCatalog) -> PresentationCitation:
    if claim_ref not in catalog.claims:
        raise EditorialCompositionError("unknown_claim_ref")
    citation = catalog.citations.get(citation_ref or "")
    if citation is None:
        raise EditorialCompositionError("unknown_citation_ref")
    if citation.claim_ref != claim_ref:
        raise EditorialCompositionError("cross_claim_citation_ref")
    return citation


def _join_frame(parts: list[str]) -> str:
    result = ""
    for part in parts:
        if not part:
            continue
        if result and not result[-1].isspace() and not part[0].isspace() and result[-1].isalnum() and part[0].isalnum():
            result += " "
        result += part
    return re.sub(r"[ \t]+", " ", result).strip()


def _append_citation_markers(text: str, refs: tuple[str, ...], catalog: AuthorizedEditorialCatalog) -> str:
    keys = tuple(sorted(dict.fromkeys(catalog.citations[ref].display_key for ref in refs), key=_citation_key))
    markers = "".join(f"[{key}]" for key in keys)
    if text[-1:] in ".!?":
        return f"{text[:-1].rstrip()} {markers}{text[-1]}"
    return f"{text.rstrip()} {markers}"


def _citation_key(value: str) -> tuple[str, int | str]:
    match = re.fullmatch(r"([^0-9]*)(\d+)", value)
    return (match.group(1), int(match.group(2))) if match else (value, value)


def _display_decimal(value: str) -> str:
    try:
        normalized = format(Decimal(str(value)), "f")
    except InvalidOperation as exc:
        raise EditorialCompositionError("invalid_numeric_authority") from exc
    integer, dot, fraction = normalized.partition(".")
    fraction = fraction.rstrip("0")
    return integer + (("," + fraction) if dot and fraction else "")


def _missing_period_display(periods: tuple[str, ...]) -> str:
    if all(re.fullmatch(r"\d{4}", value) for value in periods):
        if len(periods) == 1:
            return f"{periods[0]} рік"
        ordered = sorted(periods)
        consecutive = all(int(right) == int(left) + 1 for left, right in zip(ordered, ordered[1:]))
        return f"{ordered[0]}–{ordered[-1]} роки" if consecutive else ", ".join(ordered) + " роки"
    raise EditorialCompositionError("unsupported_limitation_period")


def _paragraph_has_supported_content(paragraph: PresentationParagraph) -> bool:
    return bool(paragraph.fact_refs or paragraph.period_refs or paragraph.claim_refs or paragraph.limitation_refs)


def _validate_presentation_report(report: PresentationReport, authority_digest: str, catalog: AuthorizedEditorialCatalog) -> None:
    if report.authority_digest != authority_digest:
        raise EditorialCompositionError("authority_digest_mismatch")
    reader_texts = [report.title]
    paragraphs = tuple(report.executive_summary.paragraphs) + tuple(p for section in report.sections for p in section.paragraphs)
    reader_texts.extend(section.title for section in report.sections)
    reader_texts.extend(paragraph.text for paragraph in paragraphs)
    for text in reader_texts:
        if "період:" in text.casefold() or "географія:" in text.casefold():
            raise EditorialCompositionError("h2_annotation_leakage")
        if re.search(r"(?i)(?<![\w-])(?:rq\d*|in\d*|finding|evidence|claim)[_-][\w-]+", text):
            raise EditorialCompositionError("internal_id_leakage")
    used = {ref for paragraph in paragraphs for ref in paragraph.citation_refs}
    if used != {item.citation_ref for item in report.citations} or any(ref not in catalog.citations for ref in used):
        raise EditorialCompositionError("citation_conformance")


def _selection_diagnostics(plan: EditorialPlan, report: PresentationReport) -> dict[str, Any]:
    return {
        "selected_claim_refs": sorted({ref for paragraph in _paragraphs(report) for ref in paragraph.claim_refs})[:64],
        "selected_fact_refs": sorted({ref for paragraph in _paragraphs(report) for ref in paragraph.fact_refs})[:64],
        "selected_period_refs": sorted({ref for paragraph in _paragraphs(report) for ref in paragraph.period_refs})[:64],
        "selected_group_refs": sorted(item.claim_group_id for item in plan.claim_groups)[:32],
        "selected_interpretation_refs": sorted(item.interpretation_id for item in plan.interpretations)[:32],
        "selected_limitation_refs": sorted(item.limitation_id for item in report.limitations)[:32],
        "resolved_citation_refs": sorted(item.citation_ref for item in report.citations)[:64],
        "rendered_fact_expressions": sorted({match for paragraph in _paragraphs(report) for match in re.findall(r"(?:понад |близько |менше ніж )?\d+(?:,\d+)?(?:%|\s+(?:млрд|млн|тис\.)?\s*(?:дол\. США|грн))", paragraph.text)})[:64],
        "rendered_period_expressions": sorted({match for paragraph in _paragraphs(report) for match in re.findall(r"(?:січ\w+|лют\w+|берез\w+|квіт\w+|трав\w+|черв\w+|лип\w+|серп\w+|верес\w+|жовт\w+|листопад\w+|груд\w+)[^,.]*?\d{4} року", paragraph.text)})[:64],
    }


def _paragraphs(report: PresentationReport) -> tuple[PresentationParagraph, ...]:
    return report.executive_summary.paragraphs + tuple(paragraph for section in report.sections for paragraph in section.paragraphs)


def _presentation_digest_payload(report: PresentationReport) -> dict[str, Any]:
    return {
        "report_id": report.report_id, "revision_number": report.revision_number,
        "authority_digest": report.authority_digest, "title": report.title,
        "paragraphs": [
            {"id": item.paragraph_id, "text": item.text, "claims": list(item.claim_refs), "citations": list(item.citation_refs)}
            for item in _paragraphs(report)
        ],
    }


def _interpretation_ref(claim_refs: tuple[str, ...], label: InterpretationLabel) -> str:
    return "ei_" + canonical_digest({"claim_refs": sorted(claim_refs), "label": label.value})


def _default_interpretation_text(label: InterpretationLabel) -> str:
    return {
        InterpretationLabel.RECOVERY: "відновлення",
        InterpretationLabel.ACCELERATION: "зростання прискорилося",
        InterpretationLabel.DECLINE: "показник знижувався",
        InterpretationLabel.INCREASE: "показник зростав",
        InterpretationLabel.DECREASE: "показник знижувався",
        InterpretationLabel.CONTRAST: "показники відрізнялися",
        InterpretationLabel.STABLE: "показник залишався стабільним",
        InterpretationLabel.MIXED: "динаміка була нерівномірною",
    }[label]


def _exact(payload: Any, fields: set[str], code: str) -> None:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise EditorialCompositionError(code)


def _string_list(value: Any, code: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise EditorialCompositionError(code)
    return value


def _error_code(error: Exception) -> str:
    if isinstance(error, EditorialCompositionError):
        return error.code
    if isinstance(error, EditorialContractError):
        return error.code.value
    return "provider_failure"


_SAFE_PROVIDER_DIAGNOSTIC_KEYS = {
    "parse_failure_category", "response_type", "content_present", "content_length",
    "finish_reason", "incomplete_reason", "decoded_root_type", "error_position",
}


def _safe_provider_diagnostics(error: Exception) -> dict[str, Any]:
    diagnostics = getattr(error, "diagnostics", None)
    if not isinstance(diagnostics, Mapping):
        return {}
    return _bounded_provider_diagnostics(diagnostics)


def _safe_adapter_diagnostics(provider: object) -> dict[str, Any]:
    diagnostics = getattr(provider, "last_diagnostics", None)
    if not isinstance(diagnostics, Mapping):
        return {}
    return _bounded_provider_diagnostics(diagnostics)


def _bounded_provider_diagnostics(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _SAFE_PROVIDER_DIAGNOSTIC_KEYS:
        if key not in diagnostics:
            continue
        value = diagnostics.get(key)
        if key in {"content_present"} and isinstance(value, bool):
            result[key] = value
        elif key in {"content_length", "error_position"} and isinstance(value, int):
            result[key] = max(0, min(value, 10_000_000))
        elif key in {"parse_failure_category", "response_type", "finish_reason", "incomplete_reason", "decoded_root_type"} and (value is None or isinstance(value, str)):
            result[key] = value[:128] if isinstance(value, str) else None
    return result


def _bounded_error(error: Exception | None) -> dict[str, Any]:
    return {"validation_codes": [_error_code(error)] if error else ["unknown"], "instruction": "return one complete corrected desk_editorial_v1 proposal"}
