"""Pure fail-closed evaluation of delivery-ready product completion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ProductCompletionStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProductCompletionFacts:
    """Typed facts collected by an application/query layer.

    This object deliberately contains no repositories or derived authority
    calculations. Digest, claim authority and provenance validation happen at
    their existing production boundaries before these facts are constructed.
    """

    run_id: str
    project_id: str
    report_id: str | None
    report_revision: int | None
    workflow_terminal: bool
    workflow_failed: bool
    research_outcome: str | None
    report_claims_valid: bool
    review_approved: bool
    review_revision_aligned: bool
    h3_authority_valid: bool
    provenance_valid: bool
    pdf_terminal: bool
    pdf_integrity_valid: bool
    pdf_provenance_valid: bool
    pptx_terminal_success: bool
    pptx_integrity_valid: bool
    pptx_provenance_valid: bool
    contradictory_identifiers: bool = False
    technical_error_code: str | None = None
    authority_diagnostic_code: str | None = None


@dataclass(frozen=True)
class ProductCompletionProjection:
    run_id: str
    report_id: str | None
    report_revision: int | None
    status: ProductCompletionStatus
    blocking_codes: tuple[str, ...]
    evaluated_at: str
    authority_diagnostic_code: str | None = None


def evaluate_product_completion(
    facts: ProductCompletionFacts,
    *,
    evaluated_at: str | None = None,
) -> ProductCompletionProjection:
    """Evaluate delivery readiness from already-authoritative persisted facts."""

    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()

    if facts.technical_error_code:
        return _projection(
            facts, ProductCompletionStatus.FAILED,
            (facts.technical_error_code,), timestamp,
        )
    if facts.contradictory_identifiers:
        return _projection(
            facts, ProductCompletionStatus.FAILED,
            ("contradictory_persisted_identifiers",), timestamp,
        )

    blocking: list[str] = []
    if not facts.workflow_terminal:
        blocking.append("workflow_not_terminal")
    if facts.workflow_failed:
        blocking.append("workflow_failed")
    if facts.research_outcome != "COMPLETED":
        blocking.append("research_outcome_not_completed")
    if not facts.report_id or facts.report_revision is None:
        blocking.append("report_missing")
    if not facts.report_claims_valid:
        blocking.append("report_claims_invalid_or_missing")
    if not facts.review_approved:
        blocking.append("h3_review_not_approved")
    if not facts.review_revision_aligned:
        blocking.append("h3_review_revision_mismatch")
    if not facts.h3_authority_valid:
        blocking.append("h3_authority_invalid")
    elif facts.authority_diagnostic_code:
        blocking.append("h3_authority_invalid")
    if not facts.provenance_valid:
        blocking.append("provenance_invalid")
    if not facts.pdf_terminal:
        blocking.append("pdf_not_terminal")
    if not facts.pdf_integrity_valid:
        blocking.append("pdf_integrity_invalid")
    if not facts.pdf_provenance_valid:
        blocking.append("pdf_provenance_invalid")
    if not facts.pptx_terminal_success:
        blocking.append("pptx_not_terminal_success")
    if not facts.pptx_integrity_valid:
        blocking.append("pptx_integrity_invalid")
    if not facts.pptx_provenance_valid:
        blocking.append("pptx_provenance_invalid")

    status = ProductCompletionStatus.READY if not blocking else ProductCompletionStatus.NOT_READY
    return _projection(facts, status, tuple(blocking), timestamp)


def _projection(
    facts: ProductCompletionFacts,
    status: ProductCompletionStatus,
    blocking_codes: tuple[str, ...],
    evaluated_at: str,
) -> ProductCompletionProjection:
    return ProductCompletionProjection(
        run_id=facts.run_id,
        report_id=facts.report_id,
        report_revision=facts.report_revision,
        status=status,
        blocking_codes=blocking_codes,
        evaluated_at=evaluated_at,
        authority_diagnostic_code=facts.authority_diagnostic_code,
    )
