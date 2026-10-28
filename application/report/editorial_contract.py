from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from application.report.claim_contract import canonical_digest
from application.report.claim_numeric_composition import build_fact_catalog
from domain.reports.report_claim import NumericFact, ReportClaim


EDITORIAL_CONTRACT_VERSION = "desk_editorial_v1"


class EditorialDiagnosticCode(str, Enum):
    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"
    MALFORMED_UNIT = "malformed_unit_discriminator"
    DUPLICATE_ID = "duplicate_id"
    DUPLICATE_UNIT_OWNERSHIP = "duplicate_unit_ownership"
    UNKNOWN_UNIT = "unknown_unit"
    ORPHAN_UNIT = "orphan_unit"
    UNKNOWN_CLAIM = "unknown_claim_ref"
    UNKNOWN_FACT = "unknown_fact_ref"
    CROSS_CLAIM_FACT = "cross_claim_fact_ref"
    UNKNOWN_PERIOD = "unknown_period_ref"
    CROSS_CLAIM_PERIOD = "cross_claim_period_ref"
    UNKNOWN_CITATION = "unknown_citation_ref"
    CROSS_CLAIM_CITATION = "cross_claim_citation_ref"
    UNKNOWN_GROUP = "unknown_claim_group"
    ORPHAN_GROUP = "orphan_claim_group"
    INCOMPATIBLE_GROUP = "incompatible_claim_group"
    UNKNOWN_INTERPRETATION = "unknown_interpretation"
    UNSUPPORTED_INTERPRETATION = "unsupported_interpretation"
    UNKNOWN_LIMITATION = "unknown_limitation"
    TEXT_DIGIT_LEAKAGE = "text_digit_leakage"
    INTERNAL_ID_LEAKAGE = "internal_id_leakage"
    URL_LEAKAGE = "url_leakage"
    H2_ANNOTATION_LEAKAGE = "h2_annotation_leakage"
    ORPHAN_CITATION = "orphan_citation"
    MISSING_EXECUTIVE_UNIT = "missing_executive_unit"
    INVALID_PRESENTATION_REPORT = "invalid_presentation_report"
    INVALID_LIMITATION = "invalid_coverage_limitation"


class EditorialContractError(ValueError):
    def __init__(self, code: EditorialDiagnosticCode, message: str = "") -> None:
        self.code = code
        super().__init__(message or code.value)


class EditorialUnitType(str, Enum):
    TEXT = "TEXT"
    CLAIM_REF = "CLAIM_REF"
    FACT_REF = "FACT_REF"
    PERIOD_REF = "PERIOD_REF"
    CITATION_REF = "CITATION_REF"
    CLAIM_GROUP_REF = "CLAIM_GROUP_REF"
    INTERPRETATION_REF = "INTERPRETATION_REF"
    LIMITATION_REF = "LIMITATION_REF"


class ClaimGroupRelation(str, Enum):
    TREND = "trend"
    COMPARISON = "comparison"
    CONTRAST = "contrast"
    SEQUENCE = "sequence"


class InterpretationLabel(str, Enum):
    RECOVERY = "recovery"
    ACCELERATION = "acceleration"
    DECLINE = "decline"
    INCREASE = "increase"
    DECREASE = "decrease"
    CONTRAST = "contrast"
    STABLE = "stable"
    MIXED = "mixed"


class MissingDimension(str, Enum):
    PERIOD = "period"
    NOMINAL_LEVEL = "nominal_level"
    REAL_LEVEL = "real_level"
    GROWTH_RATE = "growth_rate"
    GEOGRAPHY = "geography"
    CATEGORY = "category"
    CHANNEL = "channel"
    REGIONAL_DETAIL = "regional_detail"
    DRIVER = "driver"
    BENCHMARK = "benchmark"
    SOURCE_RECENCY = "source_recency"
    OTHER_BOUNDED = "other_bounded"


class CoverageStatus(str, Enum):
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    INCOMPLETE_SERIES = "incomplete_series"


class ImpactLabel(str, Enum):
    LIMITS_COMPARABILITY = "limits_comparability"
    LIMITS_TREND_INFERENCE = "limits_trend_inference"
    LIMITS_GENERALIZATION = "limits_generalization"
    REQUIRES_CAUTION = "requires_caution"


class EvidenceRequirementLabel(str, Enum):
    ADDITIONAL_PERIODS = "additional_periods"
    CURRENT_SOURCE = "current_source"
    COMPARABLE_METRIC = "comparable_metric"
    REGIONAL_EVIDENCE = "regional_evidence"
    CATEGORY_EVIDENCE = "category_evidence"
    CHANNEL_EVIDENCE = "channel_evidence"
    BENCHMARK_EVIDENCE = "benchmark_evidence"


class PresentationQualifier(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_INTERNAL_PREFIX = re.compile(r"(?i)(?<![\w-])(?:rq\d*|in\d*|finding|evidence|claim|source|citation)[_-][\w-]+")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_H2 = re.compile(r"(?i)(?:\(\s*період\s*:|географія\s*:|метрика\s*:|показник\s*:|популяція\s*:|група\s*:)")


def validate_provider_text(text: str, *, known_ids: Iterable[str] = ()) -> None:
    value = str(text).strip()
    if _URL.search(value):
        raise EditorialContractError(EditorialDiagnosticCode.URL_LEAKAGE)
    if _H2.search(value):
        raise EditorialContractError(EditorialDiagnosticCode.H2_ANNOTATION_LEAKAGE)
    folded = value.casefold()
    if _UUID.search(value) or _INTERNAL_PREFIX.search(value) or any(
        identifier and identifier.casefold() in folded for identifier in known_ids
    ):
        raise EditorialContractError(EditorialDiagnosticCode.INTERNAL_ID_LEAKAGE)
    if any(char.isdigit() for char in value):
        raise EditorialContractError(EditorialDiagnosticCode.TEXT_DIGIT_LEAKAGE)


@dataclass(frozen=True)
class EditorialUnit:
    unit_id: str
    type: EditorialUnitType
    text: str | None = None
    claim_ref: str | None = None
    fact_ref: str | None = None
    period_ref: str | None = None
    citation_ref: str | None = None
    claim_group_ref: str | None = None
    interpretation_ref: str | None = None
    limitation_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            raise EditorialContractError(EditorialDiagnosticCode.MALFORMED_UNIT)
        expected = {
            EditorialUnitType.TEXT: {"text"},
            EditorialUnitType.CLAIM_REF: {"claim_ref"},
            EditorialUnitType.FACT_REF: {"claim_ref", "fact_ref"},
            EditorialUnitType.PERIOD_REF: {"claim_ref", "period_ref"},
            EditorialUnitType.CITATION_REF: {"claim_ref", "citation_ref"},
            EditorialUnitType.CLAIM_GROUP_REF: {"claim_group_ref"},
            EditorialUnitType.INTERPRETATION_REF: {"interpretation_ref"},
            EditorialUnitType.LIMITATION_REF: {"limitation_ref"},
        }[self.type]
        present = {
            name for name in (
                "text", "claim_ref", "fact_ref", "period_ref", "citation_ref",
                "claim_group_ref", "interpretation_ref", "limitation_ref",
            ) if getattr(self, name) is not None
        }
        if present != expected or any(not str(getattr(self, name)).strip() for name in expected):
            raise EditorialContractError(EditorialDiagnosticCode.MALFORMED_UNIT)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EditorialUnit:
        try:
            allowed = {"unit_id", "type", "text", "claim_ref", "fact_ref", "period_ref", "citation_ref", "claim_group_ref", "interpretation_ref", "limitation_ref"}
            if set(payload) - allowed:
                raise ValueError
            return cls(
                unit_id=str(payload["unit_id"]), type=EditorialUnitType(str(payload["type"])),
                **{key: payload.get(key) for key in allowed - {"unit_id", "type"}},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EditorialContractError(EditorialDiagnosticCode.MALFORMED_UNIT) from exc


@dataclass(frozen=True)
class EditorialSectionPlan:
    section_id: str
    title: str
    purpose: str
    unit_ids: tuple[str, ...]
    title_is_system_owned: bool = False


@dataclass(frozen=True)
class EditorialClaimGroup:
    claim_group_id: str
    claim_refs: tuple[str, ...]
    relation: ClaimGroupRelation

    def __post_init__(self) -> None:
        if not self.claim_group_id or len(self.claim_refs) < 2 or len(set(self.claim_refs)) != len(self.claim_refs):
            raise EditorialContractError(EditorialDiagnosticCode.INCOMPATIBLE_GROUP)


@dataclass(frozen=True)
class EditorialInterpretation:
    interpretation_id: str
    claim_refs: tuple[str, ...]
    interpretation_label: InterpretationLabel
    provider_text: str

    def __post_init__(self) -> None:
        if not self.interpretation_id or not self.claim_refs:
            raise EditorialContractError(EditorialDiagnosticCode.UNSUPPORTED_INTERPRETATION)
        validate_provider_text(self.provider_text)


@dataclass(frozen=True)
class PresentationFact:
    fact_ref: str
    claim_ref: str
    numeric_fact: NumericFact
    period_refs: tuple[str, ...]
    qualifier: PresentationQualifier = PresentationQualifier.EXACT


@dataclass(frozen=True)
class PresentationPeriod:
    period_ref: str
    claim_ref: str
    fact_ref: str
    period: str


@dataclass(frozen=True)
class PresentationCitation:
    citation_ref: str
    claim_ref: str
    citation_id: str
    source_id: str
    title: str
    canonical_url: str
    display_key: str


@dataclass(frozen=True)
class CoverageLimitation:
    limitation_id: str
    topic_ref: str
    supported_claim_refs: tuple[str, ...]
    supported_period_refs: tuple[str, ...]
    missing_dimensions: tuple[MissingDimension, ...]
    missing_periods: tuple[str, ...]
    coverage_status: CoverageStatus
    impact_label: ImpactLabel
    evidence_requirement_labels: tuple[EvidenceRequirementLabel, ...]

    def __post_init__(self) -> None:
        if not self.limitation_id or not self.topic_ref or not self.missing_dimensions:
            raise EditorialContractError(EditorialDiagnosticCode.INVALID_LIMITATION)


@dataclass(frozen=True)
class EditorialPlan:
    contract_version: str
    report_title: str
    executive_summary_unit_ids: tuple[str, ...]
    sections: tuple[EditorialSectionPlan, ...]
    units: tuple[EditorialUnit, ...]
    claim_groups: tuple[EditorialClaimGroup, ...] = ()
    interpretations: tuple[EditorialInterpretation, ...] = ()
    limitation_refs: tuple[str, ...] = ()
    title_is_system_owned: bool = False


@dataclass(frozen=True)
class PresentationSection:
    section_id: str
    title: str
    unit_ids: tuple[str, ...]
    paragraphs: tuple[PresentationParagraph, ...] = ()


@dataclass(frozen=True)
class PresentationExecutiveSummary:
    unit_ids: tuple[str, ...]
    paragraphs: tuple[PresentationParagraph, ...] = ()


@dataclass(frozen=True)
class PresentationParagraph:
    paragraph_id: str
    text: str
    unit_ids: tuple[str, ...]
    claim_refs: tuple[str, ...]
    fact_refs: tuple[str, ...]
    period_refs: tuple[str, ...]
    citation_refs: tuple[str, ...]
    limitation_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.paragraph_id or not self.text.strip() or not self.unit_ids:
            raise EditorialContractError(EditorialDiagnosticCode.INVALID_PRESENTATION_REPORT)


@dataclass(frozen=True)
class PresentationReport:
    contract_version: str
    report_id: str
    revision_number: int
    source_report_id: str
    authority_digest: str
    title: str
    executive_summary: PresentationExecutiveSummary
    sections: tuple[PresentationSection, ...]
    limitations: tuple[CoverageLimitation, ...]
    citations: tuple[PresentationCitation, ...]

    def __post_init__(self) -> None:
        if self.contract_version != EDITORIAL_CONTRACT_VERSION or not all((self.report_id, self.source_report_id, self.authority_digest, self.title)) or self.revision_number < 1:
            raise EditorialContractError(EditorialDiagnosticCode.INVALID_PRESENTATION_REPORT)


@dataclass(frozen=True)
class AuthorizedClaim:
    claim_ref: str
    research_question_refs: tuple[str, ...]
    information_need_refs: tuple[str, ...]
    finding_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    fact_refs: tuple[str, ...]
    period_refs: tuple[str, ...]
    citation_refs: tuple[str, ...]
    compatible_interpretation_labels: tuple[InterpretationLabel, ...]
    grouping_dimensions: tuple[str, ...]


@dataclass(frozen=True)
class AuthorizedEditorialCatalog:
    claims: Mapping[str, AuthorizedClaim]
    facts: Mapping[str, PresentationFact]
    periods: Mapping[str, PresentationPeriod]
    citations: Mapping[str, PresentationCitation]
    limitations: Mapping[str, CoverageLimitation]

    def __post_init__(self) -> None:
        for name in ("claims", "facts", "periods", "citations", "limitations"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    @property
    def known_ids(self) -> tuple[str, ...]:
        values: set[str] = set(self.claims) | set(self.facts) | set(self.periods) | set(self.citations) | set(self.limitations)
        for claim in self.claims.values():
            values.update(claim.research_question_refs)
            values.update(claim.information_need_refs)
            values.update(claim.finding_refs)
            values.update(claim.evidence_refs)
            values.update(claim.source_refs)
        return tuple(sorted(values))


def build_authorized_editorial_catalog(
    claims: tuple[ReportClaim, ...], *, citation_registry: Mapping[str, Mapping[str, Any]],
    limitations: tuple[CoverageLimitation, ...] = (),
    fact_qualifiers: Mapping[str, PresentationQualifier] | None = None,
) -> AuthorizedEditorialCatalog:
    claim_map: dict[str, AuthorizedClaim] = {}
    facts: dict[str, PresentationFact] = {}
    periods: dict[str, PresentationPeriod] = {}
    citations: dict[str, PresentationCitation] = {}
    limitation_map = {item.limitation_id: item for item in limitations}
    if len(limitation_map) != len(limitations):
        raise EditorialContractError(EditorialDiagnosticCode.DUPLICATE_ID)
    for claim in sorted(claims, key=lambda item: item.claim_id):
        if claim.claim_id in claim_map:
            raise EditorialContractError(EditorialDiagnosticCode.DUPLICATE_ID)
        h2_catalog = build_fact_catalog(claim_id=claim.claim_id, facts=claim.scope.numeric_facts, periods=())
        fact_refs: list[str] = []
        period_refs: list[str] = []
        for fact_ref, fact in h2_catalog.facts.items():
            owned_period_refs: list[str] = []
            for period in fact.periods:
                period_ref = "ep_" + canonical_digest({"claim_ref": claim.claim_id, "fact_ref": fact_ref, "period": period})
                periods[period_ref] = PresentationPeriod(period_ref, claim.claim_id, fact_ref, period)
                owned_period_refs.append(period_ref)
                period_refs.append(period_ref)
            qualifier = (fact_qualifiers or {}).get(fact_ref, PresentationQualifier.EXACT)
            facts[fact_ref] = PresentationFact(fact_ref, claim.claim_id, fact, tuple(owned_period_refs), qualifier)
            fact_refs.append(fact_ref)
        citation_refs: list[str] = []
        for citation_id in sorted(claim.citation_ids):
            entry = citation_registry.get(citation_id)
            if not isinstance(entry, Mapping):
                continue
            source_id = str(entry.get("source_id", "")).strip()
            if not source_id or source_id not in claim.source_ids:
                continue
            citation_ref = "ec_" + canonical_digest({"claim_ref": claim.claim_id, "citation_id": citation_id, "source_id": source_id})
            citations[citation_ref] = PresentationCitation(
                citation_ref, claim.claim_id, citation_id, source_id,
                str(entry.get("title", "")), str(entry.get("canonical_url", "")), citation_id,
            )
            citation_refs.append(citation_ref)
        labels = _claim_interpretation_labels(claim)
        claim_map[claim.claim_id] = AuthorizedClaim(
            claim.claim_id, claim.research_question_ids, claim.information_need_ids,
            claim.finding_ids, claim.evidence_ids, claim.source_ids, tuple(fact_refs),
            tuple(period_refs), tuple(citation_refs), labels, _grouping_dimensions(claim),
        )
    _validate_limitations(limitation_map, claim_map, periods)
    return AuthorizedEditorialCatalog(claim_map, facts, periods, citations, limitation_map)


def deterministic_group_id(claim_refs: tuple[str, ...], relation: ClaimGroupRelation) -> str:
    return "eg_" + canonical_digest({"claim_refs": sorted(claim_refs), "relation": relation.value})


def validate_claim_group(group: EditorialClaimGroup, catalog: AuthorizedEditorialCatalog) -> None:
    if any(ref not in catalog.claims for ref in group.claim_refs):
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_CLAIM)
    if group.claim_group_id != deterministic_group_id(group.claim_refs, group.relation):
        raise EditorialContractError(EditorialDiagnosticCode.INCOMPATIBLE_GROUP)
    claims = [catalog.claims[ref] for ref in group.claim_refs]
    dimensions = [item.grouping_dimensions for item in claims]
    if not dimensions or any(item != dimensions[0] for item in dimensions[1:]):
        raise EditorialContractError(EditorialDiagnosticCode.INCOMPATIBLE_GROUP)
    facts = [catalog.facts[ref] for claim in claims for ref in claim.fact_refs]
    if len(facts) < 2:
        raise EditorialContractError(EditorialDiagnosticCode.INCOMPATIBLE_GROUP)
    period_sets = [{period.period for ref in claim.period_refs if (period := catalog.periods.get(ref))} for claim in claims]
    if group.relation in {ClaimGroupRelation.TREND, ClaimGroupRelation.SEQUENCE} and (any(not values for values in period_sets) or len({tuple(sorted(item)) for item in period_sets}) < 2):
        raise EditorialContractError(EditorialDiagnosticCode.INCOMPATIBLE_GROUP)


def validate_interpretation(item: EditorialInterpretation, catalog: AuthorizedEditorialCatalog) -> None:
    validate_provider_text(item.provider_text, known_ids=catalog.known_ids)
    if any(ref not in catalog.claims for ref in item.claim_refs):
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_CLAIM)
    common = set.intersection(*(set(catalog.claims[ref].compatible_interpretation_labels) for ref in item.claim_refs))
    if item.interpretation_label not in common:
        if item.interpretation_label == InterpretationLabel.CONTRAST and len(item.claim_refs) >= 2:
            group = EditorialClaimGroup(deterministic_group_id(item.claim_refs, ClaimGroupRelation.CONTRAST), item.claim_refs, ClaimGroupRelation.CONTRAST)
            validate_claim_group(group, catalog)
            return
        if item.interpretation_label == InterpretationLabel.ACCELERATION and _acceleration_supported(item.claim_refs, catalog):
            return
        raise EditorialContractError(EditorialDiagnosticCode.UNSUPPORTED_INTERPRETATION)


def validate_editorial_plan(plan: EditorialPlan, catalog: AuthorizedEditorialCatalog) -> None:
    if plan.contract_version != EDITORIAL_CONTRACT_VERSION:
        raise EditorialContractError(EditorialDiagnosticCode.UNSUPPORTED_CONTRACT_VERSION)
    units = _unique_map(plan.units, "unit_id")
    sections = _unique_map(plan.sections, "section_id")
    groups = _unique_map(plan.claim_groups, "claim_group_id")
    interpretations = _unique_map(plan.interpretations, "interpretation_id")
    if not plan.title_is_system_owned:
        validate_provider_text(plan.report_title, known_ids=catalog.known_ids)
    used_units: list[str] = list(plan.executive_summary_unit_ids)
    if not plan.executive_summary_unit_ids or any(ref not in units for ref in plan.executive_summary_unit_ids):
        raise EditorialContractError(EditorialDiagnosticCode.MISSING_EXECUTIVE_UNIT)
    for section in sections.values():
        if not section.title_is_system_owned:
            validate_provider_text(section.title, known_ids=catalog.known_ids)
        validate_provider_text(section.purpose, known_ids=catalog.known_ids)
        if any(ref not in units for ref in section.unit_ids):
            raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_UNIT)
        used_units.extend(section.unit_ids)
    if len(used_units) != len(set(used_units)):
        raise EditorialContractError(EditorialDiagnosticCode.DUPLICATE_UNIT_OWNERSHIP)
    if set(units) != set(used_units):
        raise EditorialContractError(EditorialDiagnosticCode.ORPHAN_UNIT)
    used_groups: set[str] = set()
    used_citations: set[str] = set()
    for unit in units.values():
        _validate_unit(unit, catalog, groups, interpretations)
        if unit.claim_group_ref:
            used_groups.add(unit.claim_group_ref)
        if unit.citation_ref:
            used_citations.add(unit.citation_ref)
    for group in groups.values():
        validate_claim_group(group, catalog)
    if set(groups) != used_groups:
        raise EditorialContractError(EditorialDiagnosticCode.ORPHAN_GROUP)
    for item in interpretations.values():
        validate_interpretation(item, catalog)
    for ref in plan.limitation_refs:
        if ref not in catalog.limitations:
            raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_LIMITATION)
    selected_citations = {unit.citation_ref for unit in units.values() if unit.type == EditorialUnitType.CITATION_REF}
    if used_citations != selected_citations:
        raise EditorialContractError(EditorialDiagnosticCode.ORPHAN_CITATION)


def _validate_unit(unit: EditorialUnit, catalog: AuthorizedEditorialCatalog, groups: Mapping[str, EditorialClaimGroup], interpretations: Mapping[str, EditorialInterpretation]) -> None:
    if unit.type == EditorialUnitType.TEXT:
        validate_provider_text(unit.text or "", known_ids=catalog.known_ids)
    elif unit.type == EditorialUnitType.CLAIM_REF:
        _require_claim(unit.claim_ref, catalog)
    elif unit.type == EditorialUnitType.FACT_REF:
        _require_claim(unit.claim_ref, catalog)
        fact = catalog.facts.get(unit.fact_ref or "")
        if fact is None:
            raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_FACT)
        if fact.claim_ref != unit.claim_ref:
            raise EditorialContractError(EditorialDiagnosticCode.CROSS_CLAIM_FACT)
    elif unit.type == EditorialUnitType.PERIOD_REF:
        _require_claim(unit.claim_ref, catalog)
        period = catalog.periods.get(unit.period_ref or "")
        if period is None:
            raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_PERIOD)
        if period.claim_ref != unit.claim_ref:
            raise EditorialContractError(EditorialDiagnosticCode.CROSS_CLAIM_PERIOD)
    elif unit.type == EditorialUnitType.CITATION_REF:
        _require_claim(unit.claim_ref, catalog)
        citation = catalog.citations.get(unit.citation_ref or "")
        if citation is None:
            raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_CITATION)
        if citation.claim_ref != unit.claim_ref:
            raise EditorialContractError(EditorialDiagnosticCode.CROSS_CLAIM_CITATION)
    elif unit.type == EditorialUnitType.CLAIM_GROUP_REF and unit.claim_group_ref not in groups:
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_GROUP)
    elif unit.type == EditorialUnitType.INTERPRETATION_REF and unit.interpretation_ref not in interpretations:
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_INTERPRETATION)
    elif unit.type == EditorialUnitType.LIMITATION_REF and unit.limitation_ref not in catalog.limitations:
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_LIMITATION)


def _require_claim(ref: str | None, catalog: AuthorizedEditorialCatalog) -> None:
    if ref not in catalog.claims:
        raise EditorialContractError(EditorialDiagnosticCode.UNKNOWN_CLAIM)


def _unique_map(items: Iterable[Any], attribute: str) -> dict[str, Any]:
    values = {getattr(item, attribute): item for item in items}
    items_tuple = tuple(items)
    if len(values) != len(items_tuple):
        raise EditorialContractError(EditorialDiagnosticCode.DUPLICATE_ID)
    return values


def _claim_interpretation_labels(claim: ReportClaim) -> tuple[InterpretationLabel, ...]:
    labels: list[InterpretationLabel] = []
    mapping = {
        "increase": InterpretationLabel.INCREASE,
        "decrease": InterpretationLabel.DECREASE,
        "stable": InterpretationLabel.STABLE,
        "mixed": InterpretationLabel.MIXED,
    }
    if claim.direction in mapping:
        labels.append(mapping[claim.direction])
    if claim.direction == "decrease":
        labels.append(InterpretationLabel.DECLINE)
    return tuple(labels)


def _grouping_dimensions(claim: ReportClaim) -> tuple[str, ...]:
    facts = claim.scope.numeric_facts
    return (
        "metric=" + "|".join(sorted(claim.scope.metrics)),
        "country=" + "|".join(sorted(claim.scope.geography_country)),
        "subnational=" + "|".join(sorted(claim.scope.geography_subnational)),
        "population=" + "|".join(sorted(claim.scope.population_dimensions)),
        "units=" + "|".join(sorted({f"{item.unit}:{item.scale}" for item in facts})),
    )


def _acceleration_supported(claim_refs: tuple[str, ...], catalog: AuthorizedEditorialCatalog) -> bool:
    if len(claim_refs) < 2:
        return False
    claims = [catalog.claims.get(ref) for ref in claim_refs]
    if any(item is None or InterpretationLabel.INCREASE not in item.compatible_interpretation_labels for item in claims):
        return False
    if any(item.grouping_dimensions != claims[0].grouping_dimensions for item in claims[1:]):
        return False
    values: list[Decimal] = []
    periods: list[str] = []
    for claim in claims:
        if len(claim.fact_refs) != 1 or len(claim.period_refs) != 1:
            return False
        try:
            values.append(Decimal(catalog.facts[claim.fact_refs[0]].numeric_fact.value))
        except InvalidOperation:
            return False
        periods.append(catalog.periods[claim.period_refs[0]].period)
    ordered = sorted(zip(periods, values), key=lambda item: item[0])
    return len(set(periods)) == len(periods) and all(left[1] < right[1] for left, right in zip(ordered, ordered[1:]))


def _validate_limitations(limitations: Mapping[str, CoverageLimitation], claims: Mapping[str, AuthorizedClaim], periods: Mapping[str, PresentationPeriod]) -> None:
    for item in limitations.values():
        if any(ref not in claims for ref in item.supported_claim_refs) or any(ref not in periods for ref in item.supported_period_refs):
            raise EditorialContractError(EditorialDiagnosticCode.INVALID_LIMITATION)
