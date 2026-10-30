"""H3 editorial, review and canonical-delivery boundary.

This module deliberately works only with the H3 typed rendering substrate.  It
does not inspect rendered prose to recover authority and does not alter the H2
editorial or review paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from application.report.claim_contract import canonical_digest
from application.report.h3_claim_generation import restore_h3_claim_structure
from application.report.typed_rendering import (
    H3AuthorityCatalog, H3_CONTRACT_VERSION, H3_LOCALE, H3_RENDERER_VERSION,
    TypedRenderDocument, TypedRenderError, TypedRenderNode,
    authority_input_digest, render_typed_document, typed_ast_digest,
    rendered_output_digest, validate_typed_render_document,
)
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim


H3_PRESENTATION_VERSION = "desk_h3_structural_presentation_v1"


class H3EditorialError(ValueError):
    def __init__(self, code: str, *, repairable: bool = False) -> None:
        self.code = code
        self.repairable = repairable
        super().__init__(code)


class H3ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class H3EditorialCatalog:
    claims: Mapping[str, Mapping[str, Any]]
    authority: H3AuthorityCatalog
    claim_set_digest: str
    authority_digest: str
    coverage_contract_digest: str
    source_workflow_run_id: str
    report_workflow_run_id: str


@dataclass(frozen=True)
class H3PresentationEnvelope:
    contract_version: str
    report_id: str
    revision_number: int
    source_report_id: str
    claim_ids: tuple[str, ...]
    typed_document: TypedRenderDocument
    authority_digest: str
    claim_set_digest: str
    coverage_contract_digest: str
    source_workflow_run_id: str
    report_workflow_run_id: str
    locale: str
    renderer_version: str
    rendered_presentation: str
    ast_digest: str
    presentation_digest: str
    render_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "report_id": self.report_id,
            "revision_number": self.revision_number,
            "source_report_id": self.source_report_id,
            "claim_ids": list(self.claim_ids),
            "typed_document": self.typed_document.to_dict(),
            "authority_digest": self.authority_digest,
            "claim_set_digest": self.claim_set_digest,
            "coverage_contract_digest": self.coverage_contract_digest,
            "source_workflow_run_id": self.source_workflow_run_id,
            "report_workflow_run_id": self.report_workflow_run_id,
            "locale": self.locale,
            "renderer_version": self.renderer_version,
            "rendered_presentation": self.rendered_presentation,
            "ast_digest": self.ast_digest,
            "presentation_digest": self.presentation_digest,
            "render_digest": self.render_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "H3PresentationEnvelope":
        required = {
            "contract_version", "report_id", "revision_number", "source_report_id",
            "claim_ids", "typed_document", "authority_digest", "claim_set_digest",
            "coverage_contract_digest", "source_workflow_run_id",
            "report_workflow_run_id", "locale", "renderer_version",
            "rendered_presentation", "ast_digest", "presentation_digest", "render_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise H3EditorialError("h3_presentation_schema")
        return cls(
            contract_version=str(payload["contract_version"]),
            report_id=str(payload["report_id"]), revision_number=int(payload["revision_number"]),
            source_report_id=str(payload["source_report_id"]),
            claim_ids=tuple(str(item) for item in payload["claim_ids"]),
            typed_document=TypedRenderDocument.from_dict(payload["typed_document"]),
            authority_digest=str(payload["authority_digest"]),
            claim_set_digest=str(payload["claim_set_digest"]),
            coverage_contract_digest=str(payload["coverage_contract_digest"]),
            source_workflow_run_id=str(payload["source_workflow_run_id"]),
            report_workflow_run_id=str(payload["report_workflow_run_id"]),
            locale=str(payload["locale"]), renderer_version=str(payload["renderer_version"]),
            rendered_presentation=str(payload["rendered_presentation"]),
            ast_digest=str(payload["ast_digest"]),
            presentation_digest=str(payload["presentation_digest"]),
            render_digest=str(payload["render_digest"]),
        )


@dataclass(frozen=True)
class H3ReviewResult:
    decision: H3ReviewDecision
    review_id: str
    report_id: str
    revision_number: int
    issues: tuple[Mapping[str, Any], ...] = ()
    provider_call_count: int = 1


@dataclass(frozen=True)
class H3DeliveryArtifact:
    kind: str
    report_id: str
    revision_number: int
    content: bytes
    provenance: Mapping[str, Any]


def load_approved_h3_delivery(*, report: Report, review, claims: tuple[ReportClaim, ...]):
    """Adapt an approved H3 presentation to the shared delivery DTO."""
    from application.deliverables.approved_delivery_provenance import ApprovedDeliveryProvenance
    from application.deliverables.editorial_delivery import (
        ApprovedEditorialDelivery, CanonicalDeliveryDocument, DeliveryParagraph,
        DeliveryReference, DeliverySection,
    )
    from domain.reviews.review_verdict import ReviewVerdict

    if review.verdict is not ReviewVerdict.APPROVE:
        raise H3EditorialError("h3_delivery_requires_approved_review")
    if (review.project_id, review.workflow_run_id, review.report_id) != (
        report.project_id, report.workflow_run_id, report.id,
    ):
        raise H3EditorialError("h3_review_lineage_mismatch")
    raw = report.metadata.get("h3_presentation")
    if not isinstance(raw, Mapping):
        raise H3EditorialError("h3_presentation_missing")
    presentation = H3PresentationEnvelope.from_dict(raw)
    coverage_digest = presentation.coverage_contract_digest
    deterministic_h3_pre_review(
        report=report, claims=claims, presentation=presentation,
        coverage_contract_digest=coverage_digest,
    )
    provenance = ApprovedDeliveryProvenance(
        report_id=report.id, revision_number=report.revision_number,
        authority_digest=presentation.authority_digest,
        presentation_digest=presentation.presentation_digest,
        review_id=review.id,
        source_workflow_run_id=presentation.source_workflow_run_id,
        report_workflow_run_id=presentation.report_workflow_run_id,
        claim_set_digest=presentation.claim_set_digest,
        coverage_contract_digest=presentation.coverage_contract_digest,
    )
    catalog = build_h3_editorial_catalog(
        report=report, claims=claims,
        coverage_contract_digest=presentation.coverage_contract_digest,
    )
    citation_display_keys = {
        item.citation_ref: item.display_key
        for item in catalog.authority.citations.values()
    }
    citation_keys = tuple(dict.fromkeys(
        citation_display_keys[node.authority_ref]
        for node in presentation.typed_document.nodes
        if node.node_type.value == "CITATION_REF"
        and node.authority_ref in citation_display_keys
    ))
    paragraph = DeliveryParagraph(
        text=presentation.rendered_presentation,
        citation_keys=citation_keys,
        claim_refs=presentation.claim_ids,
    )
    document = CanonicalDeliveryDocument(
        provenance=provenance,
        report_contract_version=H3_PRESENTATION_VERSION,
        title=report.title,
        executive_summary=(paragraph,),
        sections=(DeliverySection("H3 structural presentation", (paragraph,)),),
        limitations=tuple(report.limitations),
        references=tuple(
            DeliveryReference(item.display_key, item.display_key, "", item.source_id)
            for item in catalog.authority.citations.values()
        ),
        structural_provenance={
            "contract_version": presentation.contract_version,
            "ast_digest": presentation.ast_digest,
            "renderer_version": presentation.renderer_version,
            "locale": presentation.locale,
            "render_digest": presentation.render_digest,
            "presentation_digest": presentation.presentation_digest,
            "claim_set_digest": presentation.claim_set_digest,
            "authority_digest": presentation.authority_digest,
            "source_workflow_run_id": presentation.source_workflow_run_id,
            "report_workflow_run_id": presentation.report_workflow_run_id,
        },
    )
    return ApprovedEditorialDelivery(presentation, claims, provenance, document)


def presentation_catalog_citations(report: Report, presentation: H3PresentationEnvelope, claims: tuple[ReportClaim, ...]):
    catalog = build_h3_editorial_catalog(
        report=report, claims=claims,
        coverage_contract_digest=presentation.coverage_contract_digest,
    )
    return tuple(catalog.authority.citations.values())


class H3EditorialProvider(Protocol):
    def compose(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class H3ReviewProvider(Protocol):
    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


def build_h3_editorial_catalog(
    *, report: Report, claims: tuple[ReportClaim, ...], coverage_contract_digest: str,
) -> H3EditorialCatalog:
    if report.metadata.get("structured_claim_contract") != H3_CONTRACT_VERSION:
        raise H3EditorialError("h3_report_contract_required")
    if not claims or len({item.claim_id for item in claims}) != len(claims):
        raise H3EditorialError("h3_claim_set_invalid")
    claim_payloads: dict[str, Mapping[str, Any]] = {}
    catalogs: list[H3AuthorityCatalog] = []
    source_run: str | None = None
    report_run: str | None = None
    for claim in claims:
        document, catalog = restore_h3_claim_structure(claim)
        if document.owner_id != claim.claim_id or claim.claim_id not in catalog.claims:
            raise H3EditorialError("h3_claim_structure_ownership")
        if source_run is None:
            source_run, report_run = claim.source_workflow_run_id, claim.report_workflow_run_id
        if claim.source_workflow_run_id != source_run or claim.report_workflow_run_id != report_run:
            raise H3EditorialError("h3_claim_lineage_mismatch")
        claim_payloads[claim.claim_id] = {
            "claim_id": claim.claim_id,
            "research_question_ids": list(claim.research_question_ids),
            "information_need_ids": list(claim.information_need_ids),
            "finding_ids": list(claim.finding_ids),
            "evidence_ids": list(claim.evidence_ids),
            "source_ids": list(claim.source_ids),
            "citation_ids": list(claim.citation_ids),
            "authority_digest": claim.authority_digest,
            "ast_digest": claim.structural_assertion["typed_ast_digest"],
        }
        catalogs.append(catalog)
    authority = _merge_catalogs(catalogs)
    claim_set_digest = canonical_digest([claim_payloads[key] for key in sorted(claim_payloads)])
    return H3EditorialCatalog(
        claims=claim_payloads, authority=authority,
        claim_set_digest=claim_set_digest,
        authority_digest=authority_input_digest(authority),
        coverage_contract_digest=coverage_contract_digest,
        source_workflow_run_id=str(source_run), report_workflow_run_id=str(report_run),
    )


def compose_h3_editorial(
    *, report: Report, catalog: H3EditorialCatalog, provider: H3EditorialProvider,
    revision_number: int | None = None,
) -> H3PresentationEnvelope:
    attempts = 0
    last_error: Exception | None = None
    for attempt in range(2):
        attempts += 1
        try:
            request = {
                "contract_version": H3_CONTRACT_VERSION,
                "role": "organize_typed_references_and_numeric_free_text",
                "authority_digest": catalog.authority_digest,
                "claim_set_digest": catalog.claim_set_digest,
                "coverage_contract_digest": catalog.coverage_contract_digest,
                "claims": list(catalog.claims.values()),
                "authority_catalog": catalog.authority.to_canonical_dict(),
                "response_schema": {"fields": ["contract_version", "typed_document"]},
            }
            if attempt:
                request["repair"] = True
                request["previous_error"] = _bounded_error(last_error)
            raw = provider.compose(request)
            document = _decode_editorial_document(raw)
            validate_typed_render_document(document, catalog.authority)
            rendered = render_typed_document(document, catalog.authority)
            if document.owner_id != report.id:
                raise H3EditorialError("h3_presentation_report_ownership")
            revision = revision_number or report.revision_number
            return H3PresentationEnvelope(
                contract_version=H3_PRESENTATION_VERSION,
                report_id=report.id, revision_number=revision,
                source_report_id=report.id, claim_ids=tuple(sorted(catalog.claims)),
                typed_document=document, authority_digest=catalog.authority_digest,
                claim_set_digest=catalog.claim_set_digest,
                coverage_contract_digest=catalog.coverage_contract_digest,
                source_workflow_run_id=catalog.source_workflow_run_id,
                report_workflow_run_id=catalog.report_workflow_run_id,
                locale=rendered.locale, renderer_version=rendered.renderer_version,
                rendered_presentation=rendered.text, ast_digest=rendered.ast_digest,
                presentation_digest=canonical_digest({
                    "contract_version": H3_PRESENTATION_VERSION,
                    "typed_document": document.to_dict(),
                    "authority_digest": catalog.authority_digest,
                    "claim_set_digest": catalog.claim_set_digest,
                    "coverage_contract_digest": catalog.coverage_contract_digest,
                    "source_workflow_run_id": catalog.source_workflow_run_id,
                    "report_workflow_run_id": catalog.report_workflow_run_id,
                    "ast_digest": rendered.ast_digest,
                    "renderer_version": rendered.renderer_version,
                    "locale": rendered.locale,
                    "render_digest": rendered.render_digest,
                }), render_digest=rendered.render_digest,
            )
        except H3EditorialError as exc:
            last_error = exc
            if not exc.repairable or attempt:
                raise
        except TypedRenderError as exc:
            last_error = exc
            if attempt:
                raise H3EditorialError(exc.code.value, repairable=False) from exc
        except (KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt:
                raise H3EditorialError("h3_editorial_provider_invalid", repairable=False) from exc
    raise H3EditorialError("h3_editorial_failed") from last_error


def deterministic_h3_pre_review(
    *, report: Report, claims: tuple[ReportClaim, ...], presentation: H3PresentationEnvelope,
    coverage_contract_digest: str,
) -> None:
    if presentation.contract_version != H3_PRESENTATION_VERSION:
        raise H3EditorialError("h3_presentation_contract_mismatch")
    if presentation.report_id != report.id or presentation.source_report_id != report.id:
        raise H3EditorialError("h3_presentation_report_mismatch")
    if presentation.revision_number != report.revision_number:
        raise H3EditorialError("h3_presentation_revision_mismatch")
    catalog = build_h3_editorial_catalog(
        report=report, claims=claims, coverage_contract_digest=coverage_contract_digest,
    )
    if presentation.claim_set_digest != catalog.claim_set_digest:
        raise H3EditorialError("h3_claim_set_digest_mismatch")
    if presentation.authority_digest != catalog.authority_digest:
        raise H3EditorialError("h3_authority_digest_mismatch")
    if presentation.coverage_contract_digest != coverage_contract_digest:
        raise H3EditorialError("h3_coverage_digest_mismatch")
    if presentation.source_workflow_run_id != catalog.source_workflow_run_id:
        raise H3EditorialError("h3_source_workflow_lineage_mismatch")
    if presentation.report_workflow_run_id != catalog.report_workflow_run_id:
        raise H3EditorialError("h3_report_workflow_lineage_mismatch")
    validate_typed_render_document(presentation.typed_document, catalog.authority)
    rendered = render_typed_document(
        presentation.typed_document, catalog.authority,
        locale=presentation.locale, renderer_version=presentation.renderer_version,
    )
    if rendered.text != presentation.rendered_presentation or rendered.ast_digest != presentation.ast_digest or rendered.render_digest != presentation.render_digest:
        raise H3EditorialError("h3_presentation_render_integrity")
    expected_presentation_digest = canonical_digest({
        "contract_version": H3_PRESENTATION_VERSION,
        "typed_document": presentation.typed_document.to_dict(),
        "authority_digest": presentation.authority_digest,
        "claim_set_digest": presentation.claim_set_digest,
        "coverage_contract_digest": presentation.coverage_contract_digest,
        "source_workflow_run_id": presentation.source_workflow_run_id,
        "report_workflow_run_id": presentation.report_workflow_run_id,
        "ast_digest": presentation.ast_digest,
        "renderer_version": presentation.renderer_version,
        "locale": presentation.locale,
        "render_digest": presentation.render_digest,
    })
    if presentation.presentation_digest != expected_presentation_digest:
        raise H3EditorialError("h3_presentation_digest_mismatch")
    if presentation.typed_document.owner_id != report.id:
        raise H3EditorialError("h3_presentation_owner_mismatch")


def run_h3_review_cycle(
    *, report: Report, claims: tuple[ReportClaim, ...], presentation: H3PresentationEnvelope,
    coverage_contract_digest: str, review_provider: H3ReviewProvider,
    revision_provider: H3EditorialProvider | None = None,
) -> tuple[H3PresentationEnvelope, H3ReviewResult]:
    deterministic_h3_pre_review(
        report=report, claims=claims, presentation=presentation,
        coverage_contract_digest=coverage_contract_digest,
    )
    review_calls = 1
    decision, issues = _review_once(review_provider, report, presentation)
    if decision is H3ReviewDecision.APPROVE:
        return presentation, H3ReviewResult(decision, "h3-review-1", report.id, report.revision_number, tuple(issues), review_calls)
    if decision is not H3ReviewDecision.REVISE or revision_provider is None:
        return presentation, H3ReviewResult(decision, "h3-review-1", report.id, report.revision_number, tuple(issues), review_calls)
    revised = compose_h3_editorial(report=report, catalog=build_h3_editorial_catalog(report=report, claims=claims, coverage_contract_digest=coverage_contract_digest), provider=revision_provider, revision_number=report.revision_number)
    if _factual_signature(revised.typed_document) != _factual_signature(presentation.typed_document):
        raise H3EditorialError("h3_revision_factual_mutation")
    deterministic_h3_pre_review(report=report, claims=claims, presentation=revised, coverage_contract_digest=coverage_contract_digest)
    decision2, issues2 = _review_once(review_provider, report, revised)
    return revised, H3ReviewResult(decision2, "h3-review-2", report.id, report.revision_number, tuple(issues2), review_calls + 2)


def build_h3_canonical_delivery(
    *, report: Report, claims: tuple[ReportClaim, ...], presentation: H3PresentationEnvelope,
    review: H3ReviewResult, coverage_contract_digest: str,
) -> dict[str, Any]:
    if review.decision is not H3ReviewDecision.APPROVE:
        raise H3EditorialError("h3_delivery_requires_approved_review")
    deterministic_h3_pre_review(report=report, claims=claims, presentation=presentation, coverage_contract_digest=coverage_contract_digest)
    return {
        "contract_version": H3_PRESENTATION_VERSION,
        "report_id": report.id, "revision_number": report.revision_number,
        "source_workflow_run_id": presentation.source_workflow_run_id,
        "report_workflow_run_id": presentation.report_workflow_run_id,
        "claim_ids": list(presentation.claim_ids),
        "authority_digest": presentation.authority_digest,
        "claim_set_digest": presentation.claim_set_digest,
        "coverage_contract_digest": presentation.coverage_contract_digest,
        "ast_digest": presentation.ast_digest,
        "renderer_version": presentation.renderer_version,
        "render_digest": presentation.render_digest,
        "presentation_digest": presentation.presentation_digest,
        "markdown": presentation.rendered_presentation,
    }


def make_h3_delivery_artifact(*, kind: str, delivery: Mapping[str, Any], content: bytes) -> H3DeliveryArtifact:
    if kind not in {"pdf", "pptx"}:
        raise H3EditorialError("h3_delivery_artifact_kind")
    return H3DeliveryArtifact(
        kind=kind, report_id=str(delivery["report_id"]),
        revision_number=int(delivery["revision_number"]), content=content,
        provenance={key: delivery[key] for key in (
            "contract_version", "authority_digest", "claim_set_digest",
            "coverage_contract_digest", "ast_digest", "renderer_version",
            "render_digest", "presentation_digest", "source_workflow_run_id",
            "report_workflow_run_id",
        )},
    )


def _merge_catalogs(catalogs: list[H3AuthorityCatalog]) -> H3AuthorityCatalog:
    merged: dict[str, dict[str, Any]] = {key: {} for key in ("claims", "facts", "periods", "citations", "limitations", "interpretations")}
    forbidden: list[str] = []
    for catalog in catalogs:
        for name in merged:
            for key, value in getattr(catalog, name).items():
                if key in merged[name] and merged[name][key] != value:
                    raise H3EditorialError("h3_authority_catalog_collision")
                merged[name][key] = value
        forbidden.extend(catalog.forbidden_source_names)
    return H3AuthorityCatalog(**merged, forbidden_source_names=tuple(sorted(set(forbidden))))


def _decode_editorial_document(payload: Any) -> TypedRenderDocument:
    if not isinstance(payload, Mapping) or set(payload) != {"contract_version", "typed_document"}:
        raise H3EditorialError("h3_editorial_schema", repairable=True)
    if payload["contract_version"] != H3_CONTRACT_VERSION:
        raise H3EditorialError("h3_editorial_contract", repairable=True)
    try:
        return TypedRenderDocument.from_dict(payload["typed_document"])
    except TypedRenderError as exc:
        raise H3EditorialError(exc.code.value, repairable=True) from exc


def _review_once(provider: H3ReviewProvider, report: Report, presentation: H3PresentationEnvelope) -> tuple[H3ReviewDecision, list[Mapping[str, Any]]]:
    payload = provider.review({
        "contract_version": H3_PRESENTATION_VERSION,
        "report_id": report.id, "revision_number": report.revision_number,
        "presentation_digest": presentation.presentation_digest,
        "rendered_presentation": presentation.rendered_presentation,
        "allowed_dimensions": ["clarity", "organization", "synthesis", "repetition", "executive_summary_usefulness", "limitation_wording", "interpretation_communication"],
    })
    if not isinstance(payload, Mapping) or set(payload) != {"decision", "issues"} or not isinstance(payload["issues"], list):
        raise H3EditorialError("h3_review_schema")
    try:
        decision = H3ReviewDecision(str(payload["decision"]))
    except ValueError as exc:
        raise H3EditorialError("h3_review_decision") from exc
    issues = tuple(item for item in payload["issues"] if isinstance(item, Mapping))
    return decision, list(issues)


def _bounded_error(error: Exception | None) -> dict[str, str]:
    return {"code": str(getattr(error, "code", type(error).__name__))[:96]} if error else {}


def _factual_signature(document: TypedRenderDocument) -> tuple[tuple[str, str | None, str | None, str | None], ...]:
    return tuple(sorted(
        (node.node_type.value, node.owner_claim_ref, node.authority_ref, node.presentation_variant)
        for node in document.nodes
        if node.node_type.value in {"FACT_REF", "PERIOD_REF", "CITATION_REF", "CLAIM_REF"}
    ))
