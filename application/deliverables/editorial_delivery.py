"""Deterministic delivery projection for one exactly approved editorial Report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from application.deliverables.approved_delivery_provenance import ApprovedDeliveryProvenance
from application.deliverables.desk_finalization import claim_set_digest, coverage_contract_digest
from application.report.editorial_contract import (
    EDITORIAL_CONTRACT_VERSION,
    CoverageLimitation,
    CoverageStatus,
    EvidenceRequirementLabel,
    ImpactLabel,
    MissingDimension,
    PresentationParagraph,
)
from application.report.presentation_persistence import (
    PresentationPersistenceError,
    presentation_report_digest,
    read_presentation_report,
    report_claims_authority_digest,
)
from domain.reviews.review_verdict import ReviewVerdict


class EditorialDeliveryError(ValueError):
    pass


@dataclass(frozen=True)
class DeliveryParagraph:
    text: str
    citation_keys: tuple[str, ...]
    claim_refs: tuple[str, ...]


@dataclass(frozen=True)
class DeliverySection:
    title: str
    paragraphs: tuple[DeliveryParagraph, ...]


@dataclass(frozen=True)
class DeliveryReference:
    display_key: str
    title: str
    canonical_url: str
    source_id: str


@dataclass(frozen=True)
class CanonicalDeliveryDocument:
    provenance: ApprovedDeliveryProvenance
    report_contract_version: str
    title: str
    executive_summary: tuple[DeliveryParagraph, ...]
    sections: tuple[DeliverySection, ...]
    limitations: tuple[str, ...]
    references: tuple[DeliveryReference, ...]
    structural_provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ApprovedEditorialDelivery:
    presentation: object
    claims: tuple[object, ...]
    provenance: ApprovedDeliveryProvenance
    document: CanonicalDeliveryDocument


def load_approved_editorial_delivery(*, report, review, claims: tuple) -> ApprovedEditorialDelivery:
    if review.verdict is not ReviewVerdict.APPROVE:
        raise EditorialDeliveryError("editorial Review is not APPROVE")
    if (review.project_id, review.workflow_run_id, review.report_id) != (
        report.project_id, report.workflow_run_id, report.id,
    ):
        raise EditorialDeliveryError("editorial Review lineage mismatch")
    metadata = review.metadata
    required = {
        "report_contract_version": EDITORIAL_CONTRACT_VERSION,
        "reviewed_report_id": report.id,
        "reviewed_revision_number": report.revision_number,
        "approved_report_id": report.id,
        "approved_revision_number": report.revision_number,
    }
    if any(metadata.get(key) != value for key, value in required.items()):
        raise EditorialDeliveryError("editorial approval identity mismatch")
    if not claims:
        raise EditorialDeliveryError("editorial ReportClaims are required")
    source_runs = {item.source_workflow_run_id for item in claims}
    report_runs = {item.report_workflow_run_id for item in claims}
    if len(source_runs) != 1 or report_runs != {report.workflow_run_id}:
        raise EditorialDeliveryError("editorial workflow lineage mismatch")
    try:
        presentation = read_presentation_report(report, claims=claims)
    except PresentationPersistenceError as exc:
        raise EditorialDeliveryError("approved PresentationReport validation failed") from exc
    if presentation is None:
        raise EditorialDeliveryError("approved PresentationReport is unavailable")
    authority_digest = report_claims_authority_digest(claims)
    presentation_digest = presentation_report_digest(presentation)
    claim_digest = claim_set_digest(claims)
    coverage_digest = coverage_contract_digest(report)
    expected = {
        "authority_digest": authority_digest,
        "approved_authority_digest": authority_digest,
        "presentation_digest": presentation_digest,
        "approved_presentation_digest": presentation_digest,
        "claim_set_digest": claim_digest,
        "coverage_contract_digest": coverage_digest,
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise EditorialDeliveryError("editorial approved digest mismatch")
    provenance = ApprovedDeliveryProvenance(
        report_id=report.id,
        revision_number=report.revision_number,
        authority_digest=authority_digest,
        presentation_digest=presentation_digest,
        review_id=review.id,
        source_workflow_run_id=next(iter(source_runs)),
        report_workflow_run_id=report.workflow_run_id,
        claim_set_digest=claim_digest,
        coverage_contract_digest=coverage_digest,
    )
    document = canonical_delivery_document(presentation, provenance)
    return ApprovedEditorialDelivery(presentation, claims, provenance, document)


def canonical_delivery_document(presentation, provenance: ApprovedDeliveryProvenance) -> CanonicalDeliveryDocument:
    citations = {item.citation_ref: item for item in presentation.citations}
    seen: set[str] = set()
    ordered_refs: list[str] = []

    def paragraph(item: PresentationParagraph) -> DeliveryParagraph:
        refs = tuple(dict.fromkeys(item.citation_refs))
        if any(ref not in citations for ref in refs):
            raise EditorialDeliveryError("paragraph references an unknown citation")
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                ordered_refs.append(ref)
        return DeliveryParagraph(
            text=item.text,
            citation_keys=tuple(citations[ref].display_key for ref in refs),
            claim_refs=item.claim_refs,
        )

    summary = tuple(paragraph(item) for item in presentation.executive_summary.paragraphs)
    sections = tuple(
        DeliverySection(item.title, tuple(paragraph(value) for value in item.paragraphs))
        for item in presentation.sections
    )
    references = tuple(
        DeliveryReference(
            citations[ref].display_key,
            citations[ref].title,
            citations[ref].canonical_url,
            citations[ref].source_id,
        )
        for ref in ordered_refs
    )
    return CanonicalDeliveryDocument(
        provenance=provenance,
        report_contract_version=EDITORIAL_CONTRACT_VERSION,
        title=presentation.title,
        executive_summary=summary,
        sections=sections,
        limitations=tuple(render_coverage_limitation(item) for item in presentation.limitations),
        references=references,
    )


_DIMENSIONS = {
    MissingDimension.PERIOD: "часового охоплення",
    MissingDimension.NOMINAL_LEVEL: "номінальних показників",
    MissingDimension.REAL_LEVEL: "реальних показників",
    MissingDimension.GROWTH_RATE: "темпів зміни",
    MissingDimension.GEOGRAPHY: "географічного охоплення",
    MissingDimension.CATEGORY: "категорій",
    MissingDimension.CHANNEL: "каналів",
    MissingDimension.REGIONAL_DETAIL: "регіональної деталізації",
    MissingDimension.DRIVER: "чинників",
    MissingDimension.BENCHMARK: "порівняльної бази",
    MissingDimension.SOURCE_RECENCY: "актуальності джерел",
    MissingDimension.OTHER_BOUNDED: "окремих аспектів охоплення",
}
_REQUIREMENTS = {
    EvidenceRequirementLabel.ADDITIONAL_PERIODS: "дані за додаткові періоди",
    EvidenceRequirementLabel.CURRENT_SOURCE: "актуальніше джерело",
    EvidenceRequirementLabel.COMPARABLE_METRIC: "зіставний показник",
    EvidenceRequirementLabel.REGIONAL_EVIDENCE: "регіональні дані",
    EvidenceRequirementLabel.CATEGORY_EVIDENCE: "дані за категоріями",
    EvidenceRequirementLabel.CHANNEL_EVIDENCE: "дані за каналами",
    EvidenceRequirementLabel.BENCHMARK_EVIDENCE: "порівняльні дані",
}


def render_coverage_limitation(item: CoverageLimitation) -> str:
    dimensions = ", ".join(_DIMENSIONS[value] for value in item.missing_dimensions)
    lead = (
        "Висновок має часткове підтвердження"
        if item.coverage_status is CoverageStatus.PARTIAL
        else "Даних недостатньо для надійного висновку"
    )
    impact = {
        ImpactLabel.LIMITS_COMPARABILITY: "Це обмежує зіставлення результатів.",
        ImpactLabel.LIMITS_TREND_INFERENCE: "Це обмежує висновки про динаміку.",
        ImpactLabel.LIMITS_GENERALIZATION: "Це обмежує узагальнення результатів.",
        ImpactLabel.REQUIRES_CAUTION: "Це слід враховувати під час інтерпретації.",
    }[item.impact_label]
    requirements = tuple(_REQUIREMENTS[value] for value in item.evidence_requirement_labels)
    suffix = f" Потрібні: {', '.join(requirements)}." if requirements else ""
    return f"{lead} через прогалини {dimensions}. {impact}{suffix}"


def render_editorial_markdown(document: CanonicalDeliveryDocument) -> str:
    lines = [f"# {document.title}", "", "## Короткий виклад", ""]
    lines.extend(_paragraph_markdown(item) for item in document.executive_summary)
    for section in document.sections:
        lines.extend(("", f"## {section.title}", ""))
        lines.extend(_paragraph_markdown(item) for item in section.paragraphs)
    if document.limitations:
        lines.extend(("", "## Обмеження", ""))
        lines.extend(f"- {item}" for item in document.limitations)
    if document.references:
        lines.extend(("", "## Джерела", ""))
        for item in document.references:
            target = f" — {item.canonical_url}" if item.canonical_url else ""
            lines.append(f"- [{item.display_key}] {item.title}{target}")
    return "\n".join(lines).rstrip() + "\n"


def _paragraph_markdown(item: DeliveryParagraph) -> str:
    markers = "".join(f"[{key}]" for key in item.citation_keys)
    if not markers or markers in item.text:
        return item.text
    return f"{item.text} {markers}"
